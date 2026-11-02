ARG PREDICT_MODEL_TYPE=knn
FROM python:3.12-slim AS base

WORKDIR /app
COPY src/predict_service/requirements*.txt ./

FROM base AS knn
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS two_tower
RUN pip install --no-cache-dir -r requirements-two-tower.txt

FROM ${PREDICT_MODEL_TYPE} AS runtime
COPY src/ src/
ARG PREDICT_MODEL_TYPE=knn
ENV PREDICT_MODEL_TYPE=${PREDICT_MODEL_TYPE} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "predict_service.predict:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
