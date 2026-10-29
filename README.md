# About

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

`models/model.pkl` is a pre-trained model from the template and is still tracked in Git. A `train_model` stage will be added later.

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

The API needs `models/model.pkl` and the files in `data/processed/` (see above). Start it with:

```bash
uv run uvicorn predict_service.predict:app --app-dir src --reload
```

There is a `Makefile` provided that encapsulates this call. Type `make run-api` to run it.

Stop the API by pressing `<Ctrl + c>` in the terminal where it runs.

**In the browser:** Open <http://localhost:8000/docs>, expand `POST /predict`, click *Try it out*, enter some user ids and click *Execute*.

**With curl** (in a second terminal):

```bash
curl -X POST localhost:8000/predict -u alice:alice123 \
     -H 'Content-Type: application/json' \
     -d '{"user_ids": [21525]}'
```

The response contains 10 recommended `movieId`s per user. They are chosen randomly from the 20 nearest movies and vary from call to call. Add a seed (e.g. `"seed": 42`) to get reproducible results. Only users who rated a movie in the parts `1..split.current_part` are known. Others return `404`. For example, user `21525` is known from part 1 on, while user `1` only appears in later parts.

With the provided `Makefile` you can run this call by typing: `make test-api`.

### Authentication

The APIs need credentials, sent either with Basic auth (username and password) or as a Bearer token. The demo users are defined in `src/user_authentication_service/auth.py`:

| User    | Password   | Token         | Access                                    |
| ------- | ---------- | ------------- | ----------------------------------------- |
| `admin` | `admin123` | `admin-token` | all services (`/predict`, `/ingest`)      |
| `alice` | `alice123` | `alice-token` | only `/predict`                           |
| `bob`   | `bob123`   | `bob-token`   | only `/predict`                           |

```bash
curl -X POST localhost:8000/predict -u alice:alice123 ...                     # Basic
curl -X POST localhost:8000/predict -H 'Authorization: Bearer alice-token' ...  # Bearer
```

Missing or wrong credentials return `401`, a user without access returns `403`. In the browser docs, click *Authorize* first. See the [user authentication service](src/user_authentication_service/README.md) for how it works and how to protect a new endpoint.

## Testing the predict API Dockerfile

While the test command remains the same (`curl -X ...`) the API docker container can be started with:

```bash
docker run --rm -p 8000:8000 movie-reco-api
```

## Testing the predict API with Docker compose

### Start the project (currently the predict API)

**NOTE:** `docker compose up` and `make run-api` cannot run at the same time because both use port 8000.

```bash
docker compose up -d --build
```

Or, call the `Makefile` with

```bash
make start-project
```
Again, testing can be done with `make test-api`

### Stop the project (currently the predict API)

```bash
docker compose down
```

Or, call the `Makefile` with

```bash
make stop-project
```
