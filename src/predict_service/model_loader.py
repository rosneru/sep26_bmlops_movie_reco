"""Resolve the serving version once at startup and load its MLflow bundle."""

import json
import os
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd


def load_registered_model():
    model_type = os.getenv('PREDICT_MODEL_TYPE', 'knn').strip().lower()
    if model_type not in {'knn', 'two_tower'}:
        raise ValueError('PREDICT_MODEL_TYPE must be knn or two_tower')
    name = os.getenv(
        'PREDICT_MODEL_NAME', f'movie-genre-{model_type.replace("_", "-")}'
    )
    version = os.getenv('PREDICT_MODEL_VERSION', '').strip()
    mlflow.set_tracking_uri(
        os.getenv(
            'MLFLOW_TRACKING_URI',
            'https://dagshub.com/rosneru/sep26_bmlops_movie_reco.mlflow',
        )
    )
    mlflow.set_registry_uri(mlflow.get_tracking_uri())
    if not version or version.lower() == 'latest':
        # Resolve once to a numeric version so the model and schema come from
        # the same immutable artifact even if training registers another version.
        client = mlflow.MlflowClient()
        versions = []
        page_token = None
        while True:
            page = client.search_model_versions(
                filter_string=f"name = '{name}'",
                page_token=page_token,
            )
            versions.extend(page)
            page_token = page.token
            if not page_token:
                break
        if not versions:
            raise ValueError(f'No registered versions for {name}; run training first')
        newest = max(versions, key=lambda item: int(item.version))
        if newest.status != 'READY':
            raise ValueError(
                f'Newest version of {name} is not READY; retry after registration completes'
            )
        version = str(newest.version)
    elif not version.isascii() or not version.isdecimal() or int(version) < 1:
        raise ValueError(
            'PREDICT_MODEL_VERSION must be latest or a positive registry version'
        )
    uri = f'models:/{name}/{version}'
    directory = Path(mlflow.artifacts.download_artifacts(artifact_uri=uri))
    schema_path = directory / 'training_schema.json'
    if not schema_path.exists():
        raise ValueError(
            'Model lacks training_schema.json; retrain with the serving-bundle exporter'
        )
    schema = json.loads(schema_path.read_text())
    genres = schema['genres']
    ids = np.asarray(schema['movie_ids'])
    if not genres or len(set(genres)) != len(genres):
        raise ValueError('Invalid or duplicate model genre columns')
    if (
        ids.ndim != 1
        or not len(ids)
        or pd.isna(ids).any()
        or len(set(ids.tolist())) != len(ids)
    ):
        raise ValueError('Invalid or duplicate model movie IDs')
    metadata = mlflow.models.Model.load(str(directory / 'MLmodel')).metadata or {}
    exported_type = metadata.get('model_type') or metadata.get(
        'training_parameters', {}
    ).get('model_type')
    if exported_type != model_type:
        raise ValueError('Registered model type does not match PREDICT_MODEL_TYPE')
    if model_type == 'knn':
        from mlflow import sklearn as sklearn_flavor

        model = sklearn_flavor.load_model(str(directory))
        if schema['normalization'] != 'none':
            raise ValueError('KNN requires unnormalized input features')
        if model.n_samples_fit_ != len(ids) or model.n_features_in_ != len(genres):
            raise ValueError('KNN estimator and schema dimensions disagree')
        if list(model.feature_names_in_) != genres:
            raise ValueError('KNN estimator and schema genre order disagree')
        movie_embeddings = None
    else:
        import torch
        from mlflow import pytorch as pytorch_flavor

        model = pytorch_flavor.load_model(str(directory), map_location='cpu').eval()
        if schema['normalization'] != 'row_l2':
            raise ValueError('Two-tower requires row_l2 normalization')
        movies = np.load(directory / 'movie_features.npy', allow_pickle=False)
        if movies.shape != (len(ids), len(genres)) or not np.isfinite(movies).all():
            raise ValueError('Invalid two-tower movie feature catalog')
        with torch.inference_mode():
            movie_embeddings = model.encode_movies(
                torch.from_numpy(movies.astype(np.float32))
            )
    return ServingModel(model_type, model, genres, ids, movie_embeddings, uri)


class ServingModel:
    def __init__(self, model_type, model, genres, movie_ids, movie_embeddings, uri):
        self.model_type = model_type
        self.model = model
        self.genres = genres
        self.movie_ids = movie_ids
        self.movie_embeddings = movie_embeddings
        self.uri = uri

    def candidates(self, users, count):
        features = users.loc[:, self.genres]
        values = features.to_numpy(dtype=np.float32)
        if not np.isfinite(values).all():
            raise ValueError('User genre vectors contain NaN or infinity')
        if self.model_type == 'knn':
            return self.model.kneighbors(
                features, n_neighbors=count, return_distance=False
            )
        import torch

        norms = np.linalg.norm(values, axis=1, keepdims=True)
        if (norms == 0).any():
            raise ValueError('Two-tower cannot encode a user without genre preferences')
        with torch.inference_mode():
            users_encoded = self.model.encode_users(torch.from_numpy(values / norms))
            # Score one user at a time to avoid a request-by-catalog allocation.
            return np.stack(
                [
                    torch.topk(
                        vector @ self.movie_embeddings.T, k=count
                    ).indices.numpy()
                    for vector in users_encoded
                ]
            )
