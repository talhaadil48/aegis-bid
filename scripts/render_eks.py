"""CloudFormation for a private-node, three-zone EKS foundation. Does not deploy."""

import json
from pathlib import Path


def template():
    resources = {}

    def ref(name):
        return {"Ref": name}

    def arn(name):
        return {"Fn::GetAtt": [name, "Arn"]}

    def sub(value):
        return {"Fn::Sub": value}

    def add(name, kind, properties, **other):
        resources[name] = {"Type": "AWS::" + kind, "Properties": properties, **other}

    add("Vpc", "EC2::VPC", {"CidrBlock": "10.42.0.0/16", "EnableDnsSupport": True, "EnableDnsHostnames": True})
    add("Internet", "EC2::InternetGateway", {})
    add("AttachInternet", "EC2::VPCGatewayAttachment", {"VpcId": ref("Vpc"), "InternetGatewayId": ref("Internet")})
    add("PublicRoutes", "EC2::RouteTable", {"VpcId": ref("Vpc")})
    add(
        "InternetRoute",
        "EC2::Route",
        {"RouteTableId": ref("PublicRoutes"), "DestinationCidrBlock": "0.0.0.0/0", "GatewayId": ref("Internet")},
        DependsOn="AttachInternet",
    )
    private = []
    for i in range(3):
        zone = {"Fn::Select": [i, {"Fn::GetAZs": ""}]}
        pub, priv = f"Public{i}", f"Private{i}"
        common = [{"Key": sub("kubernetes.io/cluster/${ClusterName}"), "Value": "shared"}]
        add(
            pub,
            "EC2::Subnet",
            {
                "VpcId": ref("Vpc"),
                "CidrBlock": f"10.42.{i}.0/24",
                "AvailabilityZone": zone,
                "MapPublicIpOnLaunch": True,
                "Tags": [*common, {"Key": "kubernetes.io/role/elb", "Value": "1"}],
            },
        )
        add(
            priv,
            "EC2::Subnet",
            {
                "VpcId": ref("Vpc"),
                "CidrBlock": f"10.42.{i + 10}.0/24",
                "AvailabilityZone": zone,
                "MapPublicIpOnLaunch": False,
                "Tags": [*common, {"Key": "kubernetes.io/role/internal-elb", "Value": "1"}],
            },
        )
        private.append(ref(priv))
        add(
            f"PublicAssociation{i}",
            "EC2::SubnetRouteTableAssociation",
            {"SubnetId": ref(pub), "RouteTableId": ref("PublicRoutes")},
        )
        add(f"Address{i}", "EC2::EIP", {"Domain": "vpc"})
        add(
            f"Nat{i}",
            "EC2::NatGateway",
            {"AllocationId": {"Fn::GetAtt": [f"Address{i}", "AllocationId"]}, "SubnetId": ref(pub)},
            DependsOn="InternetRoute",
        )
        add(f"Routes{i}", "EC2::RouteTable", {"VpcId": ref("Vpc")})
        add(
            f"Egress{i}",
            "EC2::Route",
            {"RouteTableId": ref(f"Routes{i}"), "DestinationCidrBlock": "0.0.0.0/0", "NatGatewayId": ref(f"Nat{i}")},
        )
        add(
            f"PrivateAssociation{i}",
            "EC2::SubnetRouteTableAssociation",
            {"SubnetId": ref(priv), "RouteTableId": ref(f"Routes{i}")},
        )

    def role(name, service, policies):
        add(
            name,
            "IAM::Role",
            {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [{"Effect": "Allow", "Principal": {"Service": service}, "Action": "sts:AssumeRole"}],
                },
                "ManagedPolicyArns": [sub("arn:${AWS::Partition}:iam::aws:policy/" + policy) for policy in policies],
            },
        )

    add(
        "SecretsKey",
        "KMS::Key",
        {
            "EnableKeyRotation": True,
            "KeyPolicy": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": sub("arn:${AWS::Partition}:iam::${AWS::AccountId}:root")},
                        "Action": "kms:*",
                        "Resource": "*",
                    }
                ],
            },
        },
        DeletionPolicy="Retain",
        UpdateReplacePolicy="Retain",
    )
    role("ControlPlaneRole", "eks.amazonaws.com", ["AmazonEKSClusterPolicy"])
    resources["ControlPlaneRole"]["Properties"]["Policies"] = [
        {
            "PolicyName": "UseSecretsKey",
            "PolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["kms:DescribeKey", "kms:CreateGrant", "kms:Encrypt", "kms:Decrypt"],
                        "Resource": arn("SecretsKey"),
                    }
                ],
            },
        }
    ]
    role(
        "WorkerRole",
        "ec2.amazonaws.com",
        ["AmazonEKSWorkerNodePolicy", "AmazonEC2ContainerRegistryPullOnly", "AmazonEKS_CNI_Policy"],
    )
    add(
        "Cluster",
        "EKS::Cluster",
        {
            "Name": ref("ClusterName"),
            "Version": ref("KubernetesVersion"),
            "RoleArn": arn("ControlPlaneRole"),
            "DeletionProtection": True,
            "AccessConfig": {"AuthenticationMode": "API", "BootstrapClusterCreatorAdminPermissions": False},
            "EncryptionConfig": [{"Provider": {"KeyArn": arn("SecretsKey")}, "Resources": ["secrets"]}],
            "ResourcesVpcConfig": {
                "SubnetIds": private,
                "EndpointPrivateAccess": True,
                "EndpointPublicAccess": True,
                "PublicAccessCidrs": [ref("AdminCidr")],
            },
            "Logging": {
                "ClusterLogging": {
                    "EnabledTypes": [
                        {"Type": t} for t in ["api", "audit", "authenticator", "controllerManager", "scheduler"]
                    ]
                }
            },
        },
        DeletionPolicy="Retain",
        UpdateReplacePolicy="Retain",
    )
    add(
        "AdminAccess",
        "EKS::AccessEntry",
        {
            "ClusterName": ref("Cluster"),
            "PrincipalArn": ref("AdminPrincipalArn"),
            "Type": "STANDARD",
            "AccessPolicies": [
                {
                    "PolicyArn": sub(
                        "arn:${AWS::Partition}:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
                    ),
                    "AccessScope": {"Type": "cluster"},
                }
            ],
        },
    )
    add(
        "NodeTemplate",
        "EC2::LaunchTemplate",
        {
            "LaunchTemplateData": {
                "MetadataOptions": {"HttpTokens": "required", "HttpPutResponseHopLimit": 1},
                "BlockDeviceMappings": [
                    {"DeviceName": "/dev/xvda", "Ebs": {"Encrypted": True, "VolumeType": "gp3", "VolumeSize": 80}}
                ],
            }
        },
    )
    groups = []
    for i in range(3):
        name = f"Workers{i}"
        groups.append(name)
        add(
            name,
            "EKS::Nodegroup",
            {
                "ClusterName": ref("Cluster"),
                "NodeRole": arn("WorkerRole"),
                "Subnets": [private[i]],
                "InstanceTypes": [ref("InstanceType")],
                "AmiType": "AL2023_x86_64_STANDARD",
                "CapacityType": "ON_DEMAND",
                "ScalingConfig": {"MinSize": 1, "DesiredSize": 1, "MaxSize": 3},
                "LaunchTemplate": {
                    "Id": ref("NodeTemplate"),
                    "Version": {"Fn::GetAtt": ["NodeTemplate", "LatestVersionNumber"]},
                },
                "NodeRepairConfig": {"Enabled": True},
            },
            DependsOn=[f"Egress{i}"],
        )
    add(
        "PodIdentityAgent",
        "EKS::Addon",
        {"ClusterName": ref("Cluster"), "AddonName": "eks-pod-identity-agent"},
        DependsOn=groups,
    )
    add(
        "StorageRole",
        "IAM::Role",
        {
            "AssumeRolePolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "pods.eks.amazonaws.com"},
                        "Action": ["sts:AssumeRole", "sts:TagSession"],
                    }
                ],
            },
            "ManagedPolicyArns": [sub("arn:${AWS::Partition}:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy")],
        },
    )
    add(
        "StorageDriver",
        "EKS::Addon",
        {
            "ClusterName": ref("Cluster"),
            "AddonName": "aws-ebs-csi-driver",
            "PodIdentityAssociations": [{"RoleArn": arn("StorageRole"), "ServiceAccount": "ebs-csi-controller-sa"}],
        },
        DependsOn="PodIdentityAgent",
    )
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "AegisBid three-zone private-node EKS foundation; independent offsite account is provisioned separately. Creates billable infrastructure.",
        "Parameters": {
            "ClusterName": {"Type": "String", "Default": "aegis-prod"},
            "KubernetesVersion": {"Type": "String", "Default": "1.34"},
            "InstanceType": {"Type": "String", "Default": "m6i.xlarge"},
            "AdminCidr": {
                "Type": "String",
                "AllowedPattern": r"^(?:\d{1,3}\.){3}\d{1,3}/(?:[1-9]|[12]\d|3[0-2])$",
                "Description": "Restricted administrator IPv4 CIDR, preferably /32. No world-open default.",
            },
            "AdminPrincipalArn": {
                "Type": "String",
                "AllowedPattern": r"^arn:aws[^:]*:iam::\d{12}:role/.+$",
                "Description": "Existing authorized administrator role",
            },
        },
        "Resources": resources,
        "Outputs": {
            "ClusterName": {"Value": ref("Cluster")},
            "ClusterEndpoint": {"Value": {"Fn::GetAtt": ["Cluster", "Endpoint"]}},
            "VpcId": {"Value": ref("Vpc")},
        },
    }


if __name__ == "__main__":
    Path("infra/ha/eks.cloudformation.json").write_text(json.dumps(template(), indent=2))
