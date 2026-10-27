"""Original genre-based KNN recommender, integrated with MLflow."""

import json
from pathlib import Path

import mlflow.sklearn
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors


def resolve_settings(config):
    settings = {
        'n_neighbors': config.KNN_NEIGHBORS,
        'algorithm': config.KNN_ALGORITHM,
        'metric': 'euclidean',
    }

    if settings['n_neighbors'] < 1:
        raise ValueError('n_neighbors must be positive')

    if settings['algorithm'] not in {'auto', 'ball_tree', 'kd_tree', 'brute'}:
        raise ValueError('Unsupported KNN algorithm')

    return settings


def load_data(directory):
    movie_matrix = pd.read_csv(Path(directory) / 'movie_matrix.csv')

    if 'movieId' not in movie_matrix.columns:
        raise ValueError('Missing movieId column')

    if movie_matrix.empty:
        raise ValueError('Movie matrix is empty')

    movie_ids = movie_matrix['movieId']
    movie_features = movie_matrix.drop(columns=['movieId'])
    genres = movie_features.columns.tolist()

    if movie_ids.isna().any() or movie_ids.duplicated().any():
        raise ValueError('Missing or duplicate movie IDs')

    if not genres:
        raise ValueError('No genre features found')

    non_numeric = [
        col for col in genres if not pd.api.types.is_numeric_dtype(movie_features[col])
    ]
    if non_numeric:
        raise ValueError(f'Non-numeric features: {non_numeric}')

    if not np.isfinite(movie_features.to_numpy(dtype=np.float64)).all():
        raise ValueError('Movie features contain NaN or infinity')

    return {
        'movies': movie_matrix,
        'movie_ids': movie_ids,
        'genres': genres,
        'metadata': {
            'n_movies': len(movie_ids),
            'n_genres': len(genres),
            'genres': genres,
            'normalization': 'none',
            'source_file': 'movie_matrix.csv',
        },
    }


def parameters(settings, data):
    return {
        **settings,
        'model_type': 'knn',
        'n_movies': len(data['movie_ids']),
        'n_features': len(data['genres']),
        'normalization': 'none',
    }


def run_tags():
    return {
        'task': 'genre_nearest_neighbor_retrieval',
        'model_type': 'knn',
        'uses_ratings': 'false',
        'evaluation': 'not_performed',
    }


def train_model(movie_matrix, *, n_neighbors=20, algorithm='ball_tree'):
    features = movie_matrix.drop(columns=['movieId'])

    return NearestNeighbors(
        n_neighbors=n_neighbors,
        algorithm=algorithm,
        metric='euclidean',
    ).fit(features)


def train(data, settings, on_epoch=None):
    if len(data['movie_ids']) < settings['n_neighbors']:
        raise ValueError('Not enough movies for requested neighbors')

    model = train_model(
        data['movies'],
        n_neighbors=settings['n_neighbors'],
        algorithm=settings['algorithm'],
    )

    return {
        'model': model,
        'metrics': {},
    }


def registry_tags(data):
    return {
        'model_type': 'knn',
        'genres': json.dumps(data['genres']),
        'input_normalization': 'none',
        'schema_file': 'training_schema.json',
    }


def export(result, data, resolved_parameters, model_dir, *, source_root, run_id):
    """Export estimator and the matching movie-ID mapping."""

    model_dir = Path(model_dir)

    mlflow.sklearn.save_model(
        sk_model=result['model'],
        path=str(model_dir),
        serialization_format='pickle',
        pip_requirements=str(source_root / 'train_service' / 'requirements.txt'),
        metadata={
            'model_type': 'knn',
            'source_training_run_id': run_id,
            'training_parameters': resolved_parameters,
            'genres': data['genres'],
            'input_normalization': 'none',
        },
    )

    schema = {
        'genres': data['genres'],
        'movie_ids': data['movie_ids'].tolist(),
        'normalization': 'none',
    }

    (model_dir / 'training_schema.json').write_text(
        json.dumps(schema, indent=2),
        encoding='utf-8',
    )
