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
NumPy, pandas, scikit-learn and MLflow client versions. Both clients use
mlflow-skinny; only the disposable test server needs full MLflow. PyTorch is installed only in the
two-tower image. Root uv.lock is not the prediction image dependency source.

## Validation

The Compose CI uses docker-compose.test.yml to train/register a small synthetic
KNN model in its disposable local MLflow server before starting the API, then requests predictions through Nginx.
The slim clients connect over HTTP to the disposable test server, which owns the
SQLite database. They do not need server/database dependencies installed locally.
Run tests in a fresh test project (the final command deletes only its test volumes):

```bash
docker compose -p movie-reco-test -f docker-compose.yml -f docker-compose.test.yml up -d --build --wait mlflow
docker compose -p movie-reco-test -f docker-compose.yml -f docker-compose.test.yml run --rm --no-deps --build --entrypoint python \
  -e MLFLOW_TEST_TRACKING_URI=http://mlflow:5000 \
  -v "$PWD/tests:/app/tests:ro" predict \
  -m unittest discover -s /app/tests/prediction -v
docker compose -p movie-reco-test -f docker-compose.yml -f docker-compose.test.yml down -v
```

Use PREDICT_MODEL_TYPE=two_tower for optional PyTorch coverage. Synthetic tests
check the integration and alignment, not real recommendation performance.


## Airflow deployment

The final `deploy_predict` task in `training_pipeline` now deploys the exact model
version returned by training to all three Compose replicas. It preflights a
candidate, verifies `/model` and `/predict` on each replica and through nginx,
and persists the selected numeric version in root `.env`. Handled rollout errors
attempt restoration of the previous model and image. See `airflow/README.md` for
setup, expected brief interruption, verification and rollback limitations.

## Manual verification after Airflow deployment (PowerShell / Swagger)

1. In http://localhost:8081, trigger `training_pipeline` and wait for
   `prepare_features`, `train_knn`, and `deploy_predict` to succeed. This registers
   and deploys a new model version. To test the already deployed model without
   creating another version, skip this step.
2. Run `docker compose ps predict`; expect three healthy replicas.
3. Open http://localhost:8000/docs and click **Authorize**.
4. Under **HTTPBearer**, enter exactly `alice-token` (without a `Bearer` prefix),
   then click its **Authorize** button and **Close**. HTTPBasic can remain empty.
   This is a demo predict API token from `src/user_authentication_service/auth.py`,
   not a DagsHub token. Use your own API credentials if these have been changed.
5. Find valid recommendation profile IDs in the current processed data:

```powershell
Import-Csv data/processed/user_matrix.csv |
    Select-Object -First 5 userId
```

6. Expand **POST /predict**, click **Try it out**, and use an ID printed above.
   For example, use this body only if user `4` exists in your current matrix:

```json
{
  "user_ids": [4],
  "seed": 42
}
```

7. Click **Execute**. Expect HTTP `200` and `recommendations` containing the
   selected `user_id` and ten distinct `movie_ids`. The seed makes the selection
   repeatable for the same model and profile. Numeric movie IDs are returned,
   not titles or predicted rating scores.
8. Execute **GET /model** with the same authorization. Its `model_uri` must match
   the exact version printed in the corresponding training/deployment log.

Troubleshooting:

- HTTP `401`, `Invalid or missing credentials`: authorize again and re-execute.
  The generated Curl must contain `Authorization: Bearer alice-token` (or your
  configured API token). The Swagger **Authorized** label alone does not prove
  the credential is valid; the API response does.
- HTTP `404`, `Unknown user ids`: authentication passed, but the requested user
  profiles are absent from the loaded user matrix. IDs `1`, `2`, `3` are examples,
  not guaranteed profiles. Select actual IDs with the command above. The login
  account `alice` and numeric recommendation profile IDs are separate concepts.
- If a locally listed ID is still rejected, confirm the API was redeployed after
  the latest preparation. Each replica loads its user matrix only at startup.
- If Swagger's generated Curl has no Authorization header, credentials were not
  applied to that request. Authorize first, then click Execute again.

Equivalent direct request from PowerShell:

```powershell
$headers = @{ Authorization = "Bearer alice-token" }
$userId = [int](Import-Csv data/processed/user_matrix.csv |
    Select-Object -First 1).userId
$body = @{ user_ids = @($userId); seed = 42 } | ConvertTo-Json
Invoke-RestMethod http://localhost:8000/predict `
    -Method Post -Headers $headers -ContentType "application/json" -Body $body |
    ConvertTo-Json -Depth 5
Invoke-RestMethod http://localhost:8000/model -Headers $headers
```
