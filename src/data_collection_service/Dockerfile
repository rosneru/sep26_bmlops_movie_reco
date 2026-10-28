# This must be called from the project root, because the image needs
# 'uv.lock' and 'params.yaml':
#   docker build -f src/data_collection_service/Dockerfile -t movie-reco-data-collection .
FROM python:3.12-slim

# uv is a single binary, copied from the official image
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/

WORKDIR /app

# Install the dependencies first, so this layer stays cached as long as
# 'pyproject.toml' and 'uv.lock' are unchanged. '--no-default-groups' leaves
# out the groups 'dev' and 'dvc', which the API does not need.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-default-groups --no-install-project --no-cache

# Mirror the project layout, so the default paths from config.py work.
# 'data/raw/' and 'data/interim/ratings_parts/' are not copied but mounted
# as volumes (see docker-compose.yml): they are local-only and not in git.
COPY params.yaml ./
COPY src/config.py src/
COPY src/data_collection_service/main.py src/data_collection_service/ingest.py src/data_collection_service/bucket_storage_client.py src/data_collection_service/

# Use the virtual environment created by 'uv sync'
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8001
CMD ["uvicorn", "data_collection_service.main:api", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8001"]
