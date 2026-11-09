# Declare this build argument before the first FROM so it can select a stage.
ARG PREDICT_MODEL_TYPE=knn
# AS gives this stage a name that later FROM instructions can reuse.
FROM python:3.12-slim AS base

WORKDIR /app

# Both model stages start from base and install their own dependencies.
FROM base AS knn
COPY src/predict_service/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS two_tower
# requirements-two-tower.txt includes requirements.txt via -r.
COPY src/predict_service/requirements.txt src/predict_service/requirements-two-tower.txt ./
RUN pip install --no-cache-dir -r requirements-two-tower.txt

# Select knn (default) or two_tower as the parent of the final image.
# BuildKit skips the stage this image does not depend on.
FROM ${PREDICT_MODEL_TYPE} AS runtime
COPY src/predict_service/predict.py src/predict_service/model_loader.py src/predict_service/
COPY src/user_authentication_service/ src/user_authentication_service/

# Redeclare the argument inside runtime so ENV can persist it for the API.
ARG PREDICT_MODEL_TYPE
ENV PREDICT_MODEL_TYPE=${PREDICT_MODEL_TYPE} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "predict_service.predict:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
