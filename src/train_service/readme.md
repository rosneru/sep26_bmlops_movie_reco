# Two-Tower Training and MLflow

A PyTorch Two-Tower model that approximates genre similarity between users and movies. Original `(userId, movieId, rating)` interactions are not consumed by this training pipeline, so targets are generated on demand using genre cosine similarity. This does **not** demonstrate learning actual user preferences.

## Architecture and training

Each tower has independent weights:

```text
User genres  -> Linear(19, 64) -> ReLU -> Linear(64, 32) -> L2 normalization
Movie genres -> Linear(19, 64) -> ReLU -> Linear(64, 32) -> L2 normalization

Prediction = dot(user embedding, movie embedding)
Target     = cosine(user genre vector, movie genre vector)
```

The input dimension follows the preparation metadata; currently 19 usable genres remain after dropping `(no genres listed)`. Linear layers have their usual biases, but there is no separate bias added to the final similarity score.

- Adam optimizer, MSE loss; default learning rate `0.001`.
- Defaults: 10 epochs, batch size 256, 20 sampled movies per training user per epoch, CPU.
- User splits: approximately 80% train / 10% validation / 10% test; seed 42. Movie catalog is shared.
- Validation and test use fixed sampled pairs. The weights with the lowest validation RMSE are selected before test evaluation.
- RMSE/MAE measure approximation of cosine pseudo-labels. Direct cosine baseline error is approximately zero by construction. Ranking quality and real preference prediction are not evaluated by these metrics.

Settings are centralized in `src/config.py`, including split ratios, seed, model dimensions, sampling, MLflow names, URI, and serialization format (`pickle`).

## 1. Setup

Run the commands below from the repository root in **WSL Bash**, with Docker
Desktop running and WSL integration enabled. Training runs inside Docker; no
local Python environment, PyTorch or MLflow installation is required.
Configure the root `.env` from `.env.example`, including the Grafana credentials
required when Compose reads the configuration.

Training dependencies are declared in `src/train_service/requirements.txt`.
The training image does not copy the root `pyproject.toml` or `uv.lock`.
The same service requirements are explicitly included in the exported MLflow model.
Direct dependency versions are pinned; indirect dependency versions are not fully locked.
The MLflow client and server are pinned to 3.17.2, and training uses CPU-only PyTorch.

Build the images:

```bash
docker compose build train mlflow
```

Rebuild after changing training source code or requirements. Ordinary
`docker compose up` does not start training because `train` has the `training` profile.

## 2. Obtain the input matrices

Use the team's data/DVC workflow to obtain these original processed files:

```text
data/processed/user_matrix.csv
data/processed/movie_matrix.csv
```

An optional strict diagnostic is:

```bash
docker compose run --rm --no-deps train -m src.train_service.check_data
```

Training prepares its data automatically in memory: it removes exact duplicates
and invalid rows, stops on conflicting duplicate IDs, drops the missing-genre
column and zero vectors, aligns genre columns, applies row-wise L2 normalization,
and splits users. No separate preparation command is needed. The processed input
mount is read-only, and existing prepared CSVs are not used or overwritten.

## 3. Train and register

```bash
docker compose run --rm train
```

Compose starts MLflow if needed and waits for its health check. The job connects
to `http://mlflow:5000`, prepares data, trains, records parameters and metrics,
uploads preparation metadata and the model, and registers a model version.
Each invocation that completes training and registration creates a new model version.
There is currently no quality threshold for registration, and registration does not deploy the model. The temporary
model packaging directory is cleaned up, and `--rm` removes the job container.
MLflow records and artifacts persist in the `mlflow_data` volume.

Open [MLflow](http://localhost:5000). Copy the run ID and the version number from
the printed registry URI for validation:

```bash
training_run_id='REPLACE_WITH_PRINTED_RUN_ID'
model_version='REPLACE_WITH_VERSION_FROM_PRINTED_REGISTRY_URI'
```

The default registered model name is `movie-genre-two-tower`. Its version tags
include genres, normalization, label type and source training run ID.
Registering a model does not automatically deploy it to the prediction service.

## 4. Validate an existing run in Docker

The existing validator is not copied into the training image. Mount the repository's
`tests` directory read-only and invoke the script directly. These commands do not
retrain or register another model:

```bash
docker compose run --rm --no-deps \
  -e PYTHONPATH=/app \
  -v "$PWD/tests:/app/tests:ro" \
  train /app/tests/mlflow/validate_train_mlflow.py \
  --stage tracking --run-id "$training_run_id"

docker compose run --rm --no-deps \
  -e PYTHONPATH=/app \
  -v "$PWD/tests:/app/tests:ro" \
  train /app/tests/mlflow/validate_train_mlflow.py \
  --stage artifacts --run-id "$training_run_id"

docker compose run --rm --no-deps \
  -e PYTHONPATH=/app \
  -v "$PWD/tests:/app/tests:ro" \
  train /app/tests/mlflow/validate_train_mlflow.py \
  --stage registry --run-id "$training_run_id" --version "$model_version"
```

MLflow must already be healthy when using `--no-deps`. Successful stages print
`PASS`. Tracking checks parameters and metric history; artifact checks download
the model and preparation metadata; registry checks compare predictions from
the run model and registered model. Synthetic probe predictions check loading
consistency, not recommendation quality.

### Persistence after restart

Preserve the validator's snapshot in a dedicated named volume across disposable
containers:

```bash
docker volume create movie-reco-validation

docker compose run --rm --no-deps \
  -e PYTHONPATH=/app \
  -v "$PWD/tests:/app/tests:ro" \
  -v movie-reco-validation:/app/models \
  train /app/tests/mlflow/validate_train_mlflow.py \
  --stage before-restart --run-id "$training_run_id"

docker compose restart mlflow
docker compose ps mlflow
```

Wait until MLflow shows healthy, then compare:

```bash
docker compose run --rm --no-deps \
  -e PYTHONPATH=/app \
  -v "$PWD/tests:/app/tests:ro" \
  -v movie-reco-validation:/app/models \
  train /app/tests/mlflow/validate_train_mlflow.py \
  --stage after-restart --run-id "$training_run_id"
```

The snapshot is validation evidence, not a duplicate training model export.
`before-restart` refuses to overwrite an existing snapshot for the same run.

## Storage and browser UI

Open [MLflow](http://localhost:5000).

- **Experiments -> run:** Parameters, Metrics, run Tags, and Artifacts.
- **Artifacts -> data:** preparation settings, source filenames and row counts (not the input CSVs).
- **Artifacts -> model:** the loadable MLflow model, including weights, code and metadata.
- **Model registry -> movie-genre-two-tower -> version -> Tags:** visible model metadata.

Training does not retain a separate local output directory. MLflow keeps SQLite at `/mlflow/mlflow.db` and artifacts under `/mlflow/artifacts`, persisted by the named volume mounted at `/mlflow`.

Inspect the container without assuming Bash is installed:

```bash
docker compose exec mlflow sh
```

Inside the container:

```sh
cd /mlflow
ls -lah
ls -lah artifacts
exit
```

Stop services while preserving data:

```bash
docker compose stop
```

Do not use `docker compose down -v` when data must be retained: it deletes Compose-managed volumes. Starting the Prediction Service does not automatically connect it to the newly registered model.

## Files and responsibilities

```text
src/train_service/
  Dockerfile              # Build the training image
  requirements.txt        # Training and exported-model dependencies
  train_model.py          # MLflow run, training call, upload and registration
  prepare_data.py         # Clean, normalize and split inputs in memory
  check_data.py           # Shared quality checks and optional strict diagnostic
  evaluate.py             # Sampled genre-cosine RMSE and MAE
  models/
    __init__.py           # Select two_tower as the implementation
    two_tower.py          # Network, training loop and MLflow model packaging
```

Defaults are in `src/config.py`. Rebuild the training image after changing those
settings, source code or requirements; these files are copied into the image.
There is currently one model implementation, two-tower, with no KNN selector.

## What is recorded and what is not

The MLflow run records resolved parameters, per-epoch training/validation metrics,
final test metrics, descriptive tags and `data/metadata.json`. Preparation metadata
includes genre order, split settings, source filenames and row counts; it does not
contain the prepared arrays or identify an exact DVC data revision by itself.
Use the team's DVC workflow to manage the processed input versions.

The exported MLflow model includes weights, supporting code, dependency declarations,
genre metadata and resolved training parameters. It is uploaded to the run's `model`
artifact directory and registered from `runs:/<run_id>/model`.
There are no separate `checkpoint.pt`, `metrics.json` or `registration.json` exports,
and no persistent local training output directory. The temporary packaging directory
is removed after the upload and registration block finishes.

Data preparation happens inside the MLflow run. An exception during preparation,
training, export or registration marks the run failed; detailed tracebacks remain
in container logs and are not automatically uploaded to MLflow. Configuration checks
and model-setting validation happen before the run is created.

A registered version may already exist if a subsequent version-tag update fails.
Inspect the run and registry before rerunning: there is no automatic retry or rollback.
The prediction service is not switched to a new model by this training job.

## Evaluation limitations

The model learns synthetic genre-cosine targets, not observed ratings or future
user interactions. RMSE and MAE measure approximation error only. The direct cosine
baseline calculates the target itself, so its error is approximately zero by
construction; it is a sanity check rather than a competitor to beat.

Held-out user splits do not establish recommendation ranking quality. Recall@K,
NDCG@K and evaluation against held-out interactions are not implemented. The current
workflow demonstrates training, experiment tracking, model storage and registration;
it does not establish real-world recommendation quality.
