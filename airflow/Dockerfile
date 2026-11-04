FROM docker:29-cli AS docker-cli
FROM apache/airflow:3.3.2

# Static Docker CLI plus Compose; no change to Airflow or its Python packages.
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose
