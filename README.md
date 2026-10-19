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

This downloads everything the current Git commit refers to: the raw data, the split rating parts and the processed feature matrices.

### 3. The pipeline

The pipeline is defined in `dvc.yaml`. `uv run dvc dag` shows it:

```
import_raw_data -> split_data -> build_features
```

| Stage             | Does                                                                                       | Output                        |
| ----------------- | ------------------------------------------------------------------------------------------ | ----------------------------- |
| `import_raw_data` | Downloads `movies.csv` and `ratings.csv`                                                   | `data/raw/`                   |
| `split_data`      | Splits the ratings by timestamp into `split.n_parts` parts of equal size (part 1 = oldest) | `data/interim/ratings_parts/` |
| `build_features`  | Builds the user and movie matrices from the parts `1..split.current_part`                  | `data/processed/`             |

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
2. Run `uv run dvc repro`. Only `build_features` runs again. With all 8 parts it needs about 5 GB RAM.
3. Commit and push:

   ```bash
   git add params.yaml dvc.lock
   git commit -m "Use rating parts 1..2"
   uv run dvc push    # first, so the data exists on DagsHub ...
   git push           # ... before others pull the commit
   ```

Since `params.yaml` and `dvc.lock` are versioned in Git, every commit documents which data was used. `git checkout <commit>` followed by `uv run dvc checkout` restores exactly that state.

## Testing the predict API locally

The API needs `models/model.pkl` and the files in `data/processed/` (see above). Start it with:

```bash
uv run uvicorn predict.predict:app --reload
```

**In the browser:** Open <http://localhost:8000/docs>, expand `POST /predict`, click *Try it out*, enter some user ids and click *Execute*.

**With curl** (in a second terminal):

```bash
curl -X POST localhost:8000/predict \
     -H 'Content-Type: application/json' \
     -d '{"user_ids": [21525]}'
```

The response contains 10 recommended `movieId`s per user. Only users who rated a movie in the parts `1..split.current_part` are known. Others return `404`. For example, user `21525` is known from part 1 on, while user `1` only appears in later parts.
