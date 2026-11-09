# Data preparation service

One-off container that builds and validates the genre feature matrices from the
data in the DagsHub storage bucket. It reuses `features/build_features.py`
functions, the `train_service/check_data.py` checks and the bucket client of the
data collection service. It does not train a model or contact MLflow.

## Inputs and outputs

Inputs, read from the bucket that the data collection service fills:
- `movies.csv`
- `ratings_parts/ratings_01.csv` up to the highest stored part, combined
  cumulatively. With `--up-to N` only the parts `1..N` are used.

All parts from 1 to the selected one must be in the bucket, otherwise the job
fails. `params.yaml` is not read.

Outputs, replaced only after both matrices pass validation:
- `data/processed/user_matrix.csv`: per user the average genre vector of the
  rated movies (rating values are ignored)
- `data/processed/movie_matrix.csv`: binary genre vector per movie

Each file replacement is atomic, but the pair is not a transaction: do not run
preparation jobs concurrently or start training during a preparation run. The
prediction service reads the user features at startup only.

## Prerequisites

- In the root `.env`: `DAGSHUB_S3_ENDPOINT_URL`, `DAGSHUB_BUCKET` and
  `DAGSHUB_TOKEN` (see `.env.example`).
- At least rating part 1 in the bucket, uploaded by the data collection service
  (see `src/data_collection_service/README.md`).

## Run

From the repository root:

```bash
docker compose run --rm --build data_preparation             # all parts in the bucket
docker compose run --rm data_preparation --up-to 2           # only the parts 1..2
```

The service is in the `preparation` profile, so `docker compose up` does not
start it. Rebuild the image after changes to its code, Dockerfile or
requirements.

Expected log on success, exit code 0:

```text
Preparing rating parts 1..2 from bucket sep26_bmlops_movie_reco
Data preparation passed: parts=1..2, ratings=..., users=..., movies=..., genres=...
```

Any error (missing settings, unreachable bucket, missing parts, invalid data)
is logged as `Data preparation failed: ...` and exits with code 1, before the
outputs are changed. Examples:

| Command | Expected error |
|---|---|
| `--up-to 0` | `--up-to must be a positive integer` |
| `--up-to 99` | `Rating parts 1..99 are required, but the bucket contains only the parts [...]` |
| without `DAGSHUB_*` settings | `Missing configuration: set ...` |

## Airflow

The `prepare_features` task of the `training_pipeline` DAG runs this image (see
`airflow/README.md`). To reach the bucket, the task must pass the three
`DAGSHUB_*` settings and allow network access. The DAG is not adapted yet: it
still runs the container without network and mounts the old local inputs.
