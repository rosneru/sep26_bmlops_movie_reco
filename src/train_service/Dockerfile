ARG MODEL_TYPE=knn
FROM python:3.12-slim AS base

WORKDIR /app
COPY src/train_service/requirements*.txt ./

FROM base AS knn
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS two_tower
RUN pip install --no-cache-dir -r requirements-two-tower.txt

FROM ${MODEL_TYPE} AS training
COPY src/__init__.py src/config.py src/
COPY src/train_service/ src/train_service/

ARG MODEL_TYPE=knn
ENV MODEL_TYPE=${MODEL_TYPE} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["python"]
CMD ["-m", "src.train_service.train_model"]
