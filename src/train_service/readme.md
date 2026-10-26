Two-Tower Training and MLflow

A PyTorch Two-Tower model that approximates genre similarity between users and movies. Original `(userId, movieId, rating)` interactions are unavailable to this training pipeline, so targets are generated on demand using genre cosine similarity. This does **not** demonstrate learning actual user preferences.

## Architecture and training

Each tower has independent weights:

```text
User genres  -> Linear(19, 64) -> ReLU -> Linear(64, 32) -> L2 normalization
Movie genres -> Linear(19, 64) -> ReLU -> Linear(64, 32) -> L2 normalization

Prediction = dot(user embedding, movie embedding)
Target     = cosine(user genre vector, movie genre vector)
```

The input dimension follows `metadata.json`; currently 19 usable genres remain after dropping `(no genres listed)`. Linear layers have their usual biases, but there is no separate bias added to the final similarity score.

- Adam optimizer, MSE loss; default learning rate `0.001`.
- Defaults: 10 epochs, batch size 256, 20 sampled movies per training user per epoch, CPU.
- User splits: approximately 80% train / 10% validation / 10% test; seed 42. Movie catalog is shared.
- Validation and test use fixed sampled pairs. The best validation RMSE checkpoint is selected before test evaluation.
- RMSE/MAE measure approximation of cosine pseudo-labels. Direct cosine baseline error is approximately zero by construction. Ranking quality and real preference prediction are not evaluated by these metrics.

Settings are centralized in `src/config.py`, including split ratios, seed, model dimensions, sampling, MLflow names, URI, and serialization format (`pickle`).

## 1. Setup

Run all commands in **PowerShell from the repository root**. Docker Desktop must be running. Configure the root `.env` from `.env.example`, including the Grafana values required by Compose. The Git merge must be resolved before using `uv`; conflict markers in `uv.lock` prevent execution.

```powershell
uv sync
uv run python -c "import torch; import mlflow; print('PyTorch:', torch.__version__); print('MLflow:', mlflow.__version__); print('CUDA:', torch.cuda.is_available())"
```

PyTorch is already a project dependency. Use `uv add torch` only if it is missing from `pyproject.toml`; it changes dependency files. CUDA is not required for the current CPU implementation.

## 2. Start services

```powershell
docker compose up -d --build
docker compose ps
docker compose logs --tail 50 mlflow
Invoke-RestMethod -Uri 'http://localhost:5000/health'
```

Wait for a successful health response before training. To start only MLflow, use `docker compose up -d --build mlflow` instead of the full stack.

## 3. Check and prepare data

Obtain the team's matrices from DagsHub through the team's configured access method and place them here:

```text
data/processed/user_matrix.csv
data/processed/movie_matrix.csv
```

```powershell
uv run python -m src.train_service.check_data
uv run python -m src.train_service.prepare_data
```

`check_data` is a strict diagnostic; it can report issues that `prepare_data` subsequently cleans. Preparation removes exact duplicates, rejects invalid rows with reasons, stops on conflicting duplicate IDs, drops the missing-genre column and zero vectors, aligns genre columns, applies per-row L2 normalization, and splits users.

Prepared files are written to `data/processed/two_tower/`: `users_train.csv`, `users_val.csv`, `users_test.csv`, `movies.csv`, `metadata.json`, and rejected-row reports under `rejected/`. Re-running preparation overwrites these outputs; original matrices remain unchanged.

## 4. Train and register

```powershell
uv run python -m src.train_service.train_model
```

The run logs parameters, per-epoch metrics, final test metrics, input-file hashes, metadata, source files, and checkpoints. The selected model is registered as `movie-genre-two-tower`. Each successful training/registration creates a new run and model version.

Copy the **matching** values printed at the end:

```powershell
$trainingRunId = 'REPLACE_WITH_PRINTED_RUN_ID'
$modelVersion = 'REPLACE_WITH_PRINTED_MODEL_VERSION'
```

The registered version also receives visible Tags: `genres`, `input_normalization`, `label_type`, and `source_training_run_id`.

## 5. Validate the real training run

Ensure `tests/__init__.py` and `tests/mlflow/__init__.py` exist (empty files are sufficient). Use `validate_train_mlflow.py`; these commands do not retrain or register another version.

| Stage | Checks |
|---|---|
| `tracking` | Finished run, parameters, epoch history, best epoch, saved metrics |
| `artifacts` | Downloads, local/downloaded checkpoint hashes, genre schema, prediction equality |
| `registry` | Version provenance, Registry loading, prediction equality against checkpoint |
| `before-restart` / `after-restart` | Run information and artifact hashes before/after restart; checkpoint loading and predictions |

```powershell
uv run python -m tests.mlflow.validate_train_mlflow --stage tracking --run-id $trainingRunId
uv run python -m tests.mlflow.validate_train_mlflow --stage artifacts --run-id $trainingRunId
uv run python -m tests.mlflow.validate_train_mlflow --stage registry --run-id $trainingRunId --version $modelVersion
```

Successful stages print `PASS`. The artifact and persistence tests require the local `models/two_tower/<run_id>/checkpoint.pt`. Prediction comparisons use fixed synthetic probe inputs and test serialization consistency, not recommendation quality.

### Persistence after restart

```powershell
uv run python -m tests.mlflow.validate_train_mlflow --stage before-restart --run-id $trainingRunId
docker compose restart mlflow
docker compose ps mlflow
Invoke-RestMethod -Uri 'http://localhost:5000/health'
```

Once the health check succeeds:

```powershell
uv run python -m tests.mlflow.validate_train_mlflow --stage after-restart --run-id $trainingRunId
uv run python -m tests.mlflow.validate_train_mlflow --stage registry --run-id $trainingRunId --version $modelVersion
```

`before-restart` creates a local `persistence_snapshot.json` and refuses to overwrite it. If a snapshot already exists for this run, keep it and proceed to the restart/comparison. Registry Tags are not explicitly asserted by the current tests.

## Storage and browser UI

Open [MLflow](http://localhost:5000).

- **Experiments -> run:** Parameters, Metrics, run Tags, and Artifacts.
- **Artifacts -> data:** metadata and input-file hashes (not the input CSVs).
- **Artifacts -> source:** training source and config.
- **Artifacts -> training:** `checkpoint.pt`, `metrics.json`, and `registration.json`.
- **Model registry -> movie-genre-two-tower -> version -> Tags:** visible model metadata.

Local outputs are in `models/two_tower/<run_id>/`. MLflow keeps SQLite at `/mlflow/mlflow.db` and artifacts under `/mlflow/artifacts`, persisted by the named volume mounted at `/mlflow`.

Inspect the container without assuming Bash is installed:

```powershell
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

```powershell
docker compose stop
```

Do not use `docker compose down -v` when data must be retained: it deletes Compose-managed volumes. Starting the Prediction Service does not automatically connect it to the newly registered model.

## Optional legacy smoke tests

These are separate examples, not validation of the real Two-Tower run:

```powershell
uv run python -m tests.mlflow.test_mlflow
uv run python -m tests.mlflow.test_model_registry
```

`test_mlflow` logs fixed demonstration metrics and a text artifact. `test_model_registry` trains an Iris RandomForest and registers `movie-recommender-test`; it can create additional versions and depends on the installed scikit-learn/MLflow serialization support. Neither is required for the workflow above.
