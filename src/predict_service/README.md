# Prediction from the MLflow registry

Prediction connects to the shared DagsHub MLflow server and resolves the newest
registered version at startup, then downloads that
numeric version and its matching catalog. It does not train or fall back to model.pkl.
Latest means newest registered, not best evaluated. An empty registry requires an
initial training run before prediction can start. Set MLFLOW_TRACKING_USERNAME
and DAGSHUB_TOKEN in the root .env; Compose forwards them to the MLflow client.
The existing authenticated POST /predict request and response format is preserved.
GET /model (same authentication) reports the loaded model URI and type.

## KNN

From the repository root in WSL Bash:

```bash
# Create a registered candidate if needed; note the printed version.
docker compose build train
docker compose run --rm train
```

Set these in the root .env (latest is the default):

```dotenv
PREDICT_MODEL_TYPE=knn
PREDICT_MODEL_NAME=movie-genre-knn
PREDICT_MODEL_VERSION=latest
```

Then:

```bash
docker compose build predict
docker compose up -d predict nginx
curl -u alice:alice123 http://localhost:8000/model
curl -u alice:alice123 -H 'Content-Type: application/json' \
  -d '{"user_ids":[1],"seed":42}' http://localhost:8000/predict
```

Use an ID from your actual user_matrix.csv. The processed data directory is mounted
read-only, and only user_matrix.csv is consumed by prediction. Movie IDs and genre
order come from the selected model's training_schema.json, not today's movie CSV.
Extra user columns are ignored; required genres are reordered to the model schema.
Missing genres, invalid data, or unavailable/incompatible models fail clearly.

## Two-tower

Build/train with MODEL_TYPE=two_tower, then set PREDICT_MODEL_TYPE=two_tower,
PREDICT_MODEL_NAME=movie-genre-two-tower. Leave PREDICT_MODEL_VERSION=latest.
Build the two-tower prediction image and recreate predict/nginx as above.
Training and serving settings are independent. Existing two-tower versions from
before this change need retraining: the new export includes training_schema.json
and movie_features.npy with the exact cleaned, normalized training catalog.
Users are aligned to the stored genres and L2-normalized; the CPU model embeds
them and ranks the exported movie catalog by embedding dot product.
Both model types sample ten recommendations from their top twenty candidates
(or the entire catalog when fewer than twenty movies exist), retaining the seed
behavior. This integration does not establish recommendation quality.

## Deployment and rollback

Changing MODEL_TYPE alone affects training only. New registrations are loaded on
the next prediction startup, not during active requests. After training, run
`docker compose restart predict` to load the newest version. After changing
serving settings, recreate all replicas with `docker compose up -d predict nginx`.
Each replica resolves latest independently; avoid concurrent registration during
a restart if all replicas must use exactly the same version. Future Airflow work
will validate candidates and promote a champion alias before restarting prediction.
To roll back, optionally set a numeric PREDICT_MODEL_VERSION and recreate the
replicas. Set it back to latest to resume automatic selection.
Build the matching image when switching type or after source/dependency changes.
A registry outage prevents a fresh startup; already running replicas keep their
in-memory model. No live reload or offline cache fallback is implemented.

The prediction images use service-specific pinned requirements matching training's
NumPy, pandas, scikit-learn and MLflow versions. PyTorch is installed only in the
two-tower image. Root uv.lock is not the prediction image dependency source.

## Validation

The Compose CI uses docker-compose.test.yml to train/register a small synthetic
KNN model in its disposable local MLflow server before starting the API, then requests predictions through Nginx.
Local integration tests use temporary SQLite registries and artifacts:

```bash
docker run --rm --network none --entrypoint python \
  -v "$PWD/tests:/app/tests:ro" movie-reco-predict:knn \
  -m unittest discover -s /app/tests/prediction -v
```

Use the two_tower image for optional PyTorch coverage. Synthetic tests check the
integration and alignment, not real recommendation performance.
