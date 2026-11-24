"""Render namespaced multi-zone workloads. No credentials are written into the output."""

import argparse
import copy
import json
import re
from pathlib import Path
from urllib.parse import urlparse

NAMESPACE = "aegis"


def render(api_image, gateway_image, web_image, origin):
    for image in (api_image, gateway_image, web_image):
        if not re.fullmatch(r"[^\s]+@sha256:[a-f0-9]{64}", image):
            raise ValueError("Production images must use explicit sha256 digests")
    public = urlparse(origin)
    if (
        public.scheme != "https"
        or not public.hostname
        or public.path not in ("", "/")
        or public.query
        or public.fragment
    ):
        raise ValueError("Production PUBLIC_ORIGIN must be an HTTPS origin")
    origin = origin.rstrip("/")
    items = []

    def add(kind, name, spec=None, **extra):
        obj = {
            "apiVersion": {
                "Deployment": "apps/v1",
                "StatefulSet": "apps/v1",
                "PodDisruptionBudget": "policy/v1",
                "HorizontalPodAutoscaler": "autoscaling/v2",
                "Ingress": "networking.k8s.io/v1",
                "NetworkPolicy": "networking.k8s.io/v1",
            }.get(kind, "v1"),
            "kind": kind,
            "metadata": {"name": name, "namespace": NAMESPACE},
            **extra,
        }
        if spec is not None:
            obj["spec"] = spec
        items.append(obj)
        return obj

    def secret(name, key):
        return {"secretKeyRef": {"name": name, "key": key}}

    def env(name, value):
        return {"name": name, "value": value}

    database = [
        {"name": "DATABASE_URL", "valueFrom": secret("aegis-pg-app", "uri")},
        env("PGSSLMODE", "verify-full"),
        env("PGSSLROOTCERT", "/postgres-ca/ca.crt"),
    ]
    messaging = [
        {"name": "NATS_URL", "valueFrom": secret("aegis-runtime", "nats-url")},
        env("NATS_REPLICAS", "3"),
        env("NATS_CA_FILE", "/nats-ca/ca.crt"),
        env("NATS_TLS_SERVER_NAME", "nats.aegis.svc"),
    ]
    common = [env("ENVIRONMENT", "production"), env("ENABLE_CHAOS", "false"), env("PUBLIC_ORIGIN", origin)]
    volumes = [
        {"name": "tmp", "emptyDir": {}},
        {
            "name": "postgres-ca",
            "secret": {"secretName": "aegis-pg-ca", "items": [{"key": "ca.crt", "path": "ca.crt"}]},
        },
        {"name": "nats-ca", "secret": {"secretName": "aegis-nats-tls", "items": [{"key": "ca.crt", "path": "ca.crt"}]}},
    ]
    mounts = [
        {"name": "tmp", "mountPath": "/tmp"},
        {"name": "postgres-ca", "mountPath": "/postgres-ca", "readOnly": True},
        {"name": "nats-ca", "mountPath": "/nats-ca", "readOnly": True},
    ]

    def workload(name, image, port=None, command=None, environment=None, count=3):
        labels = {"app": name, "app.kubernetes.io/part-of": "aegis"}
        container = {
            "name": name,
            "image": image,
            "env": environment or [],
            "securityContext": {
                "allowPrivilegeEscalation": False,
                "readOnlyRootFilesystem": True,
                "runAsNonRoot": True,
                "runAsUser": 10001,
                "capabilities": {"drop": ["ALL"]},
            },
            "resources": {"requests": {"cpu": "250m", "memory": "256Mi"}, "limits": {"cpu": "2", "memory": "2Gi"}},
            "volumeMounts": copy.deepcopy(mounts),
        }
        if command:
            container["command"] = command
        if port:
            container["ports"] = [{"name": "http", "containerPort": port}]
            container["readinessProbe"] = {
                "httpGet": {"path": "/health", "port": port},
                "periodSeconds": 5,
                "timeoutSeconds": 6,
            }
            container["livenessProbe"] = {
                "httpGet": {"path": "/livez" if name == "api" else "/health", "port": port},
                "periodSeconds": 10,
                "timeoutSeconds": 3,
                "failureThreshold": 6,
            }
        else:
            probe = [
                "python",
                "-c",
                "import pathlib,time; assert time.time()-float(pathlib.Path('/tmp/aegis-pipeline-health').read_text())<60",
            ]
            container["readinessProbe"] = {"exec": {"command": probe}, "initialDelaySeconds": 10, "periodSeconds": 10}
        pod = {
            "metadata": {"labels": labels},
            "spec": {
                "automountServiceAccountToken": False,
                "terminationGracePeriodSeconds": 40,
                "securityContext": {"fsGroup": 10001, "seccompProfile": {"type": "RuntimeDefault"}},
                "containers": [container],
                "volumes": copy.deepcopy(volumes),
                "topologySpreadConstraints": [
                    {
                        "maxSkew": 1,
                        "minDomains": 2,
                        "nodeTaintsPolicy": "Honor",
                        "topologyKey": "topology.kubernetes.io/zone",
                        "whenUnsatisfiable": "DoNotSchedule",
                        "labelSelector": {"matchLabels": {"app": name}},
                    }
                ],
            },
        }
        deploy = add(
            "Deployment",
            name,
            {
                "replicas": count,
                "selector": {"matchLabels": {"app": name}},
                "strategy": {"type": "RollingUpdate", "rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1}},
                "template": pod,
            },
        )
        add("PodDisruptionBudget", name, {"minAvailable": 2, "selector": {"matchLabels": {"app": name}}})
        if port:
            add(
                "Service",
                name,
                {"selector": {"app": name}, "ports": [{"name": "http", "port": port, "targetPort": "http"}]},
            )
        return deploy

    api = workload(
        "api",
        api_image,
        8000,
        [
            "uvicorn",
            "aegis.api:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--proxy-headers",
            "--forwarded-allow-ips",
            "*",
        ],
        [
            *common,
            *database,
            {"name": "SESSION_SECRET", "valueFrom": secret("aegis-runtime", "session-secret")},
            {"name": "ADMISSION_SERVICE_KEY", "valueFrom": secret("aegis-runtime", "admission-key")},
            env("AUDIT_SIGNING_KEY", "/audit/audit-private.pem"),
        ],
    )
    api["spec"]["template"]["spec"]["volumes"].append({"name": "audit", "secret": {"secretName": "aegis-audit-key"}})
    api["spec"]["template"]["spec"]["containers"][0]["volumeMounts"].append(
        {"name": "audit", "mountPath": "/audit", "readOnly": True}
    )
    for name in ("worker", "relay"):
        workload(
            name,
            api_image,
            command=["python", "-m", "aegis.pipeline", name],
            environment=[*common, *database, *messaging],
        )
    gateway = workload(
        "gateway",
        gateway_image,
        8081,
        environment=[
            env("API_URL", "http://api:8000"),
            env("PUBLIC_ORIGIN", origin),
            {"name": "ADMISSION_SERVICE_KEY", "valueFrom": secret("aegis-runtime", "admission-key")},
            env("MAX_CONNECTIONS", "25000"),
            env("MAX_AUCTION_CONNECTIONS", "25000"),
            env("MAX_USER_CONNECTIONS", "10"),
        ],
    )
    gateway["spec"]["template"]["spec"]["containers"][0]["securityContext"]["runAsUser"] = 65532
    admission = workload(
        "admission",
        gateway_image,
        8081,
        environment=[
            env("API_URL", "http://api:8000"),
            env("PUBLIC_ORIGIN", origin),
            {"name": "ADMISSION_SERVICE_KEY", "valueFrom": secret("aegis-runtime", "admission-key")},
            env("GOMAXPROCS", "2"),
            env("GOMEMLIMIT", "768MiB"),
        ],
    )
    admission["spec"]["template"]["spec"]["containers"][0]["securityContext"]["runAsUser"] = 65532
    add(
        "HorizontalPodAutoscaler",
        "gateway",
        {
            "scaleTargetRef": {"apiVersion": "apps/v1", "kind": "Deployment", "name": "gateway"},
            "minReplicas": 3,
            "maxReplicas": 12,
            "metrics": [
                {
                    "type": "Resource",
                    "resource": {"name": "cpu", "target": {"type": "Utilization", "averageUtilization": 60}},
                }
            ],
            "behavior": {"scaleDown": {"stabilizationWindowSeconds": 600}},
        },
    )
    web = workload("web", web_image, 8080)
    webpod = web["spec"]["template"]["spec"]
    webpod["containers"][0]["securityContext"]["runAsUser"] = 101
    webpod["containers"][0]["readinessProbe"]["httpGet"]["path"] = "/"
    webpod["containers"][0]["livenessProbe"]["httpGet"]["path"] = "/"
    webpod["volumes"] = [{"name": "web-config", "configMap": {"name": "aegis-web"}}, {"name": "tmp", "emptyDir": {}}]
    webpod["containers"][0]["volumeMounts"] = [
        {"name": "tmp", "mountPath": "/tmp"},
        {"name": "web-config", "mountPath": "/etc/nginx/nginx.conf", "subPath": "nginx.conf", "readOnly": True},
    ]
    add(
        "ConfigMap",
        "aegis-web",
        data={
            "nginx.conf": "pid /tmp/nginx.pid; events {} http { include /etc/nginx/mime.types; client_body_temp_path /tmp/client; proxy_temp_path /tmp/proxy; fastcgi_temp_path /tmp/fastcgi; uwsgi_temp_path /tmp/uwsgi; scgi_temp_path /tmp/scgi; server { listen 8080; root /usr/share/nginx/html; location / { try_files $uri $uri.html /index.html; } } }"
        },
    )
    add(
        "Ingress",
        "aegis",
        {
            "ingressClassName": "nginx",
            "tls": [{"hosts": [public.hostname], "secretName": "aegis-public-tls"}],
            "rules": [
                {
                    "host": public.hostname,
                    "http": {
                        "paths": [
                            {
                                "path": path,
                                "pathType": "Prefix",
                                "backend": {"service": {"name": name, "port": {"number": port}}},
                            }
                            for path, name, port in [
                                ("/v1/live/", "gateway", 8081),
                                ("/v1/auctions", "admission", 8081),
                                ("/v1/", "api", 8000),
                                ("/", "web", 8080),
                            ]
                        ]
                    },
                }
            ],
        },
    )["metadata"]["annotations"] = {
        "nginx.ingress.kubernetes.io/proxy-read-timeout": "3600",
        "nginx.ingress.kubernetes.io/proxy-send-timeout": "60",
        "nginx.ingress.kubernetes.io/proxy-buffering": "off",
    }
    add("NetworkPolicy", "default-deny", {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]})
    add(
        "NetworkPolicy",
        "same-namespace-and-dns",
        {
            "podSelector": {},
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [{"from": [{"podSelector": {}}]}],
            "egress": [
                {"to": [{"podSelector": {}}]},
                {"ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]},
            ],
        },
    )
    add(
        "NetworkPolicy",
        "public-ingress",
        {
            "podSelector": {"matchLabels": {"app.kubernetes.io/part-of": "aegis"}},
            "ingress": [
                {
                    "from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "ingress-nginx"}}}],
                    "ports": [{"port": 8000}, {"port": 8080}, {"port": 8081}],
                }
            ],
        },
    )
    add(
        "NetworkPolicy",
        "postgres-control-and-backup",
        {
            "podSelector": {"matchLabels": {"cnpg.io/cluster": "aegis-pg"}},
            "ingress": [
                {
                    "from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "cnpg-system"}}}],
                    "ports": [{"port": 8000}, {"port": 5432}],
                }
            ],
            "egress": [{"ports": [{"protocol": "TCP", "port": 443}]}],
        },
    )
    add(
        "Job",
        "aegis-migrate",
        {
            "template": {
                "spec": {
                    "restartPolicy": "OnFailure",
                    "automountServiceAccountToken": False,
                    "containers": [
                        {
                            "name": "migrate",
                            "image": api_image,
                            "command": ["python", "-m", "aegis.db"],
                            "env": database,
                            "volumeMounts": [{"name": "postgres-ca", "mountPath": "/postgres-ca", "readOnly": True}],
                        }
                    ],
                    "volumes": [volumes[1]],
                }
            },
            "backoffLimit": 5,
        },
    )["apiVersion"] = "batch/v1"
    return {"apiVersion": "v1", "kind": "List", "items": items}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    for name in ("api-image", "gateway-image", "web-image", "origin", "output"):
        p.add_argument("--" + name, required=True)
    args = p.parse_args()
    result = render(args.api_image, args.gateway_image, args.web_image, args.origin)
    with Path(args.output).open("x") as stream:
        json.dump(result, stream, indent=2)
