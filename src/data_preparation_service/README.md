# Data preparation service

One-off container for building and validating genre feature matrices. It reuses
`features/build_features.py` functions and `train_service/check_data.py` checks;
it does not perform Two-Tower normalization, train a model, or contact DagsHub.

Inputs (mounted read-only):
- `data/raw/movies.csv`
- `data/interim/ratings_parts/ratings_01.csv` through the selected part
- `params.yaml`, using `split.current_part` by default

The original raw-data import/splitting remains a prerequisite, not part of this
service. The user's profile is the average genre vector of rated movies; rating
values are still ignored, preserving the existing feature-building behavior.

Run from the project root:

```powershell
docker compose run --rm --build data_preparation
```

Optional explicit part selection:

```powershell
docker compose run --rm data_preparation --current-part 2
```

Successful runs exit with code 0 and replace:
- `data/processed/user_matrix.csv`
- `data/processed/movie_matrix.csv`

The output directory is mounted writable; train/predict mount it read-only.
Invalid/missing data exits nonzero. Existing outputs are not replaced until both
new matrices pass validation and their temporary CSV files have been written.
Each file replacement is atomic but the pair is not a transaction; do not run
preparation jobs concurrently or start training during a preparation run.
The prediction service reads user features at startup, so it does not hot-reload
these changes. Coordinated deployment is a later orchestration step.

This service is in the `preparation` profile, so normal `docker compose up` does
not execute it. It is not connected to an Airflow DAG yet. No DVC lock changes,
data uploads, or MLflow registration are performed by this command; DVC's
`build_features` stage remains an alternative entry point for the existing flow.

## Manual verification (PowerShell, in order)

Run these commands from the repository root with Docker Desktop running and
the project's Python environment active. Compose also requires the existing
root `.env` settings, even though preparation itself does not contact DagsHub.

### 1. Confirm the local inputs

```powershell
Get-Content params.yaml
Test-Path data/raw/movies.csv
Get-ChildItem data/interim/ratings_parts/ratings_*.csv
```

`movies.csv` must exist (`True`), and all rating parts from 1 through
`split.current_part` must be available. `n_parts` controls the number of source
parts; `current_part` selects the cumulative range used for this run.
If the source files are missing, prepare them first (this may download the full
raw dataset and rebuild its chronological parts):

```powershell
$env:PYTHONPATH = "src"
dvc repro split_data
```

### 2. Validate Compose configuration

```powershell
docker compose config --quiet
$LASTEXITCODE
```

Expected: no configuration error and exit code `0`.

### 3. Build and execute preparation

```powershell
docker compose run --rm --build data_preparation
$LASTEXITCODE
```

Expected: `Data preparation passed: ratings=..., users=..., movies=..., genres=...`
and exit code `0`. This checks image construction, imports, local input reading,
feature creation, validation and writing both CSV outputs. The container exits
after completing the job and `--rm` removes it; output files remain on the host.

### 4. Inspect the outputs

```powershell
Get-Item data/processed/user_matrix.csv, data/processed/movie_matrix.csv |
    Select-Object Name, Length, LastWriteTime
Get-Content data/processed/user_matrix.csv -TotalCount 3
Get-Content data/processed/movie_matrix.csv -TotalCount 3
```

Both files should be nonempty and updated. Their first columns are `userId` and
`movieId` respectively, followed by matching genre columns. User features are
genre averages; movie features are binary. Successful preparation replaces the
existing processed files, so do not run it concurrently with training.

### 5. Verify rejection of an invalid argument

```powershell
docker compose run --rm data_preparation --current-part 0
$LASTEXITCODE
```

Expected: `current_part must be a positive integer` and exit code `1`.
This failure is intentional: it verifies invalid input is rejected before
outputs are changed. It is not a Docker installation error.

### 6. Optional: select a different cumulative input range

```powershell
docker compose run --rm data_preparation --current-part 2
$LASTEXITCODE
```

Requires both `ratings_01.csv` and `ratings_02.csv`. Expected: exit code `0` and
outputs rebuilt from both parts combined. This argument does not modify
`params.yaml`. Omit it to use the file's `split.current_part` again.

No separate pytest file or running Airflow services are required for these checks.
