FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY src/mlflow_service/requirements.txt .
RUN pip install -r requirements.txt

RUN mkdir -p /mlflow/artifacts

EXPOSE 5000

CMD ["mlflow", "server", \
     "--host", "0.0.0.0", \
     "--port", "5000", \
     "--workers", "1", \
     "--backend-store-uri", "sqlite:////mlflow/mlflow.db", \
     "--serve-artifacts", \
     "--artifacts-destination", "/mlflow/artifacts", \
     "--allowed-hosts", "localhost:*,127.0.0.1:*,mlflow:*"]