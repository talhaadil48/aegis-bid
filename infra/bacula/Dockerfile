FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d && chmod +x /usr/sbin/policy-rc.d && apt-get update && apt-get install -y --no-install-recommends bacula-director-pgsql bacula-sd bacula-fd bacula-console postgresql && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y --no-install-recommends bacula-director && rm -rf /var/lib/apt/lists/*
COPY infra/bacula /opt/aegis-bacula
CMD ["bash", "/opt/aegis-bacula/start.sh"]
