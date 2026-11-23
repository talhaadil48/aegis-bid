FROM postgres:18
COPY infra/pitr /opt/aegis-pitr
RUN chmod +x /opt/aegis-pitr/*.sh
ENTRYPOINT ["bash", "/opt/aegis-pitr/primary.sh"]
