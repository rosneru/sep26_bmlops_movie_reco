# This must be called from the project root, because the image needs
# 'uv.lock', 'models/' and 'data/processed/':
#   docker build -f src/predict/Dockerfile -t movie-reco-api .
FROM python:3.10-slim

# uv is a single binary, copied from the official image
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/

WORKDIR /app

# Install the dependencies first, so this layer stays cached as long as
# 'pyproject.toml' and 'uv.lock' are unchanged. '--no-default-groups' leaves
# out the groups 'dev' and 'dvc', which the API does not need.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-default-groups --no-install-project --no-cache

# Mirror the project layout, so the default paths in predict.py work
COPY models/model.pkl models/
COPY data/processed/user_matrix.csv data/processed/movie_matrix.csv data/processed/
COPY src/predict/predict.py src/predict/

# Use the virtual environment created by 'uv sync'
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
CMD ["uvicorn", "predict.predict:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
