FROM python:3.12-slim

WORKDIR /app
COPY src/data_preparation_service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Reuse feature-building and matrix validation without installing training/MLflow.
COPY src/__init__.py src/config.py src/
COPY src/features/ src/features/
COPY src/train_service/__init__.py src/train_service/check_data.py src/train_service/
COPY src/data_preparation_service/ src/data_preparation_service/

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["python", "-m", "src.data_preparation_service.main"]
