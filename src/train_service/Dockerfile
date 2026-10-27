FROM python:3.12-slim

WORKDIR /app

COPY src/train_service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/__init__.py src/config.py src/
COPY src/train_service/ src/train_service/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["python"]
CMD ["-m", "src.train_service.train_model"]
