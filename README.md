# About

Prediction now loads the latest registered MLflow model at startup. Follow the
[prediction setup](src/predict_service/README.md) before older API examples below.


Movie recommendation project, done with four members from September 2026 in a Liora MLOps training.

The project is based on Lioras [Template_MLOps_movie_recommandation](https://github.com/DataScientest-Studio/Template_MLOps_movie_recommandation) repository as a starting point.

## Development

The project package dependencies are managed with `uv`, so please ensure to [have uv installed](https://www.datacamp.com/tutorial/python-uv) and run this command after cloning the repository:

```bash
uv sync
```

## Getting started with the data

The data and pipeline outputs are not stored in Git. They are versioned with [DVC](https://dvc.org) and stored on [DagsHub](https://dagshub.com/rosneru/sep26_bmlops_movie_reco).

To simulate data that arrives over time, DagsHub only holds the data that has "arrived" so far (the rating parts `1..split.current_part`, see section 4). The complete raw data and all rating parts are the local data source and are never pushed.

The arrived data is in two places on DagsHub:

- **DVC storage:** uploaded by `dvc push` (section 4), shown in the *Files* tab under `data/`.
- **Repo bucket *DagsHub Storage*:** uploaded by the [data collection service](src/data_collection_service/README.md), shown on the repo page under *Storage Buckets*.

### 1. Get access to DagsHub (once)

1. Create a DagsHub account and ask `rosneru` to add you as a collaborator with *Write* access.
2. Create a personal token under *DagsHub → User Settings → Tokens*.
3. Store the token locally. It goes to `.dvc/config.local`, which is ignored by Git:

   ```bash
   uv run dvc remote modify origin --local access_key_id <your-token>
   uv run dvc remote modify origin --local secret_access_key <your-token>
   ```

   Repeat this on every machine you work on. Never commit tokens, and don't share them.

### 2. Download the data

```bash
uv run dvc pull
```

This downloads the data the current Git commit refers to:

- `data/ingested/`: `movies.csv` and the rating parts `1..split.current_part` that have "arrived" so far
- `data/processed/`: the user and movie matrices built from these parts

The raw data (`data/raw/`) and the complete set of rating parts (`data/interim/ratings_parts/`) are not on DagsHub. If you need them, create them locally. This downloads the raw data from the template's S3 bucket and splits it, resulting in exactly the same files on every machine:

```bash
uv run dvc repro split_data
```

### 3. The pipeline

The pipeline is defined in `dvc.yaml`. `uv run dvc dag` shows it:

```
import_raw_data -> split_data -> ingest
                              -> build_features
```

| Stage             | Does                                                                                       | Output                        | On DagsHub |
| ----------------- | ------------------------------------------------------------------------------------------ | ----------------------------- | ---------- |
| `import_raw_data` | Downloads `movies.csv` and `ratings.csv`                                                   | `data/raw/`                   | no         |
| `split_data`      | Splits the ratings by timestamp into `split.n_parts` parts of equal size (part 1 = oldest) | `data/interim/ratings_parts/` | no         |
| `ingest`          | Copies `movies.csv` and the parts `1..split.current_part` (the data that has "arrived")    | `data/ingested/`              | yes        |
| `build_features`  | Builds the user and movie matrices from the parts `1..split.current_part`                  | `data/processed/`             | yes        |

The outputs of `import_raw_data` and `split_data` have `cache: false` in `dvc.yaml`, so `dvc push` never uploads them.

Run the pipeline with:

```bash
uv run dvc repro
```

DVC only runs stages whose code, input data or parameters changed. Always use `uv run`, since the scripts need the project's virtual environment.


### 4. Simulating new data with `split.current_part`

To simulate data arriving over time, the ratings are split into 8 chronological parts (1995 to 2015, about 2.5 million ratings each). `split.current_part` in `params.yaml` decides how many of them are used:

```yaml
split:
  n_parts: 8
  current_part: 1   # use parts 1..1; increase to "receive" new data
```

To add the next part:

1. Increase `current_part` in `params.yaml`, e.g. to `2`.
2. Run `uv run dvc repro`. Only `ingest` and `build_features` run again. With all 8 parts `build_features` needs about 5 GB RAM.
3. Commit and push:

   ```bash
   git add params.yaml dvc.lock
   git commit -m "Use rating parts 1..2"
   uv run dvc push    # first, so the data exists on DagsHub ...
   git push           # ... before others pull the commit
   ```

   `dvc push` uploads the new part to the DVC storage.

Since `params.yaml` and `dvc.lock` are versioned in Git, every commit documents which data was used. `git checkout <commit>` followed by `uv run dvc pull` restores the ingested data and the matrices of that state.

Alternatively, the [data collection service](src/data_collection_service/README.md) uploads the parts to the repo bucket.

## Testing the predict API locally

The API loads its model from MLflow and reads `data/processed/user_matrix.csv` at startup. Prepare or restore the matrix and export the MLflow credentials and model selector into your shell before running Uvicorn directly. Docker Compose reads the project `.env` automatically. Start the local API with:

```bash
uv run uvicorn predict_service.predict:app --app-dir src --reload
```

There is a `Makefile` provided that encapsulates this call. Type `make run-api` to run it.

Stop the API by pressing `<Ctrl + c>` in the terminal where it runs.

**In the browser:** Open <http://localhost:8000/docs>, expand `POST /predict`, click *Try it out*, enter some user ids and click *Execute*.

**With curl** (in a second terminal):

```bash
TOKEN=$(curl -s -X POST localhost:8000/token -d 'username=alice&password=alice123' \
  | python -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
curl -X POST localhost:8000/predict -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"user_ids": [21525]}'
```

The response contains 10 recommended `movieId`s per user. They are chosen randomly from the 20 nearest movies and vary from call to call. Add a seed (e.g. `"seed": 42`) to get reproducible results. Only users who rated a movie in the parts `1..split.current_part` are known. Others return `404`. For example, user `21525` is known from part 1 on, while user `1` only appears in later parts.

With the provided `Makefile` you can run this call by typing: `make test-api`.

### Authentication

The APIs use OAuth2 with expiring tokens: log in once at `POST /token` with username and password, then send the returned token as `Authorization: Bearer <token>`. The demo users are:

| User    | Password   | Access                               |
| ------- | ---------- | ------------------------------------ |
| `admin` | `admin123` | all services (`/predict`, `/ingest`) |
| `alice` | `alice123` | only `/predict`                      |
| `bob`   | `bob123`   | only `/predict`                      |

Missing, wrong or expired credentials return `401`, a user without access returns `403`. In the browser docs, click *Authorize* and enter username and password. See the [user authentication service](src/user_authentication_service/README.md) for how it works, how to add users and how to protect a new endpoint.

## Run the end-to-end demo with Docker Compose

Run these commands from the repository root. Stop any local Uvicorn process first because Nginx also uses host port 8000.

1. Complete the [Airflow setup](airflow/README.md) and configure the DagsHub and Grafana credentials in your local `.env`. Set `MODEL_TYPE=knn` and `PREDICT_MODEL_TYPE=knn` for this DAG. Set `PREDICT_MODEL_VERSION=@live` if `live` is the agreed serving alias.
2. Ensure the DagsHub storage bucket contains `movies.csv` and at least the first rating batch. Airflow now prepares features directly from this bucket. See the [data collection guide](src/data_collection_service/README.md).
3. Build the task images and start Airflow and monitoring.

   ```bash
   docker compose config --quiet
   docker compose build data_preparation train predict
   docker compose up -d --build --wait airflow-api-server airflow-scheduler airflow-dag-processor
   docker compose up -d prometheus grafana
   ```

4. Open Airflow at <http://localhost:8081>, unpause `training_pipeline`, and trigger it. The DAG registers a numbered KNN model, tests it, and moves the serving alias. On the first deployment, the DAG starts prediction and Nginx. If switching an existing deployment to a new alias, first point it to the currently served version, then recreate prediction and the scheduler with the updated settings.
5. Open <http://localhost:8000/docs> and authenticate. Use `GET /model` to verify the deployed version and `POST /predict` with a known user to verify predictions. Open <http://localhost:3000> to see the three replicas and request metrics after the next scrape. See the [monitoring guide](src/monitoring_service/README.md).

## Prediction registry selection

The API resolves `PREDICT_MODEL_VERSION` at startup. Use an alias such as `@live` for Airflow-managed deployment, a number to pin a version, or `latest` to select the highest registered version if it is ready. Leave `PREDICT_MODEL_NAME` empty to use the default for the selected model type. See [prediction setup and rollback](src/predict_service/README.md).

## MLflow on DagsHub

Training and prediction use the shared [DagsHub MLflow dashboard](https://dagshub.com/rosneru/sep26_bmlops_movie_reco.mlflow).
Models, artifacts, runs, and registry versions live there; a local MLflow server
is not needed for normal use.

Set your DagsHub username and existing token in the root `.env`:

```dotenv
MLFLOW_TRACKING_USERNAME=your-dagshub-username
DAGSHUB_TOKEN=your-token
```

The repository MLflow URL is the default. Optionally set `MLFLOW_TRACKING_URI`
to another server. Compose passes these settings explicitly to train/predict;
MLflow uses `DAGSHUB_TOKEN` as `MLFLOW_TRACKING_PASSWORD`.

```bash
docker compose build train predict
docker compose run --rm train
docker compose up -d predict nginx
```

Training creates remote models; earlier local models are not migrated. Repository
contributor access and internet connectivity are needed. Check storage/account
limits on DagsHub; no paid plan is required by this configuration.

### Local test registry

CI uses a disposable local server, dummy credentials, and synthetic models so
it never uploads test artifacts to the team's DagsHub repository. For local
integration testing with that server, use a separate Compose project:

```bash
docker compose -p movie-reco-test -f docker-compose.yml -f docker-compose.test.yml config --quiet
```

Use the same `-p` and `-f` arguments on subsequent test commands. Normal commands
without the override use DagsHub. The separate test server is defined only in
`docker-compose.test.yml`.
