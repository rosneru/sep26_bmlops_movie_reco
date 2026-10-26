import copy
import hashlib
import json
import tempfile
from pathlib import Path

import mlflow
import mlflow.pytorch as mlflow_pytorch
import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.nn import functional as F

from src.config import (
    PROJECT_ROOT,
    TRAINING_DATA_DIR,
    MODELS_DIR,
    RANDOM_SEED as SEED,
    BATCH_SIZE,
    PAIRS_PER_USER,
    EVAL_PAIRS_PER_USER,
    EPOCHS,
    LEARNING_RATE,
    HIDDEN_DIM,
    EMBEDDING_DIM,
    MLFLOW_TRACKING_URI,
    MLFLOW_EXPERIMENT_NAME,
    MLFLOW_RUN_NAME,
    MLFLOW_REGISTERED_MODEL_NAME,
    MLFLOW_SERIALIZATION_FORMAT,
    VAL_SEED_OFFSET,
    TEST_SEED_OFFSET,
)


def validate_config():
    """Validate training settings before starting a run."""
    positive_integers = {
        'EPOCHS': EPOCHS,
        'BATCH_SIZE': BATCH_SIZE,
        'PAIRS_PER_USER': PAIRS_PER_USER,
        'EVAL_PAIRS_PER_USER': EVAL_PAIRS_PER_USER,
        'HIDDEN_DIM': HIDDEN_DIM,
        'EMBEDDING_DIM': EMBEDDING_DIM,
    }

    for name, value in positive_integers.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
        ):
            raise ValueError(
                f'{name} must be a positive integer'
            )

    if (
        not np.isfinite(LEARNING_RATE)
        or LEARNING_RATE <= 0
    ):
        raise ValueError(
            'LEARNING_RATE must be finite and positive'
        )

    # This implementation logs the model using pickle.
    # pt2 requires a separate export configuration.
    if MLFLOW_SERIALIZATION_FORMAT != 'pickle':
        raise ValueError(
            'This training script currently supports '
            "MLFLOW_SERIALIZATION_FORMAT='pickle' only"
        )

    if not MLFLOW_REGISTERED_MODEL_NAME.strip():
        raise ValueError(
            'MLFLOW_REGISTERED_MODEL_NAME cannot be empty'
        )


def load_features(path, id_column, genres):
    """Load prepared features and apply L2 normalization in memory."""
    df = pd.read_csv(path)

    if df.empty:
        raise ValueError(f'{path.name}: empty data')

    if id_column not in df.columns:
        raise ValueError(
            f'{path.name}: missing {id_column}'
        )

    ids = df[id_column]

    if (
        ids.isna().any()
        or ids.astype(str).str.strip().eq('').any()
        or ids.duplicated().any()
    ):
        raise ValueError(
            f'{path.name}: missing or duplicate IDs'
        )

    expected_columns = {id_column, *genres}

    if set(df.columns) != expected_columns:
        raise ValueError(
            f'{path.name}: unexpected feature columns'
        )

    values = df.loc[:, genres].to_numpy(
        dtype=np.float32
    )

    if (
        not np.isfinite(values).all()
        or (values < 0).any()
    ):
        raise ValueError(
            f'{path.name}: invalid feature values'
        )

    if (np.linalg.norm(values, axis=1) == 0).any():
        raise ValueError(
            f'{path.name}: zero genre vectors'
        )

    features = torch.from_numpy(values)
    features = F.normalize(features, p=2, dim=1)

    return ids.to_numpy(), features


class TwoTower(nn.Module):
    def __init__(
        self,
        input_dim,
        hidden_dim,
        embedding_dim,
    ):
        super().__init__()

        self.user_tower = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, embedding_dim),
        )

        self.movie_tower = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, embedding_dim),
        )

    def encode_users(self, features):
        return F.normalize(
            self.user_tower(features),
            p=2,
            dim=1,
        )

    def encode_movies(self, features):
        return F.normalize(
            self.movie_tower(features),
            p=2,
            dim=1,
        )

    def forward(self, users, movies):
        user_embeddings = self.encode_users(users)
        movie_embeddings = self.encode_movies(movies)

        return (
            user_embeddings * movie_embeddings
        ).sum(dim=1)


def file_sha256(path):
    digest = hashlib.sha256()

    with path.open('rb') as stream:
        for chunk in iter(
            lambda: stream.read(1024 * 1024),
            b'',
        ):
            digest.update(chunk)

    return digest.hexdigest()


@torch.no_grad()
def evaluate(model, users, movies, seed):
    """Evaluate fixed sampled pairs against genre cosine targets."""
    model.eval()

    generator = torch.Generator().manual_seed(seed)

    squared_error = 0.0
    absolute_error = 0.0
    baseline_squared_error = 0.0
    count = 0

    total_pairs = len(users) * EVAL_PAIRS_PER_USER

    for start in range(
        0,
        total_pairs,
        BATCH_SIZE,
    ):
        stop = min(
            start + BATCH_SIZE,
            total_pairs,
        )

        user_indices = (
            torch.arange(start, stop)
            // EVAL_PAIRS_PER_USER
        )

        movie_indices = torch.randint(
            len(movies),
            (stop - start,),
            generator=generator,
        )

        batch_users = users[user_indices]
        batch_movies = movies[movie_indices]

        # Dot product equals cosine for normalized inputs.
        targets = (
            batch_users * batch_movies
        ).sum(dim=1)

        predictions = model(
            batch_users,
            batch_movies,
        )

        if not torch.isfinite(predictions).all().item():
            raise RuntimeError(
                'Non-finite predictions during evaluation'
            )

        errors = predictions - targets

        squared_error += (
            errors.square().sum().item()
        )
        absolute_error += (
            errors.abs().sum().item()
        )

        baseline_predictions = F.cosine_similarity(
            batch_users,
            batch_movies,
            dim=1,
        )

        baseline_squared_error += (
            (baseline_predictions - targets)
            .square()
            .sum()
            .item()
        )

        count += len(targets)

    if count == 0:
        raise ValueError(
            'No evaluation pairs available'
        )

    return {
        'rmse': float(
            np.sqrt(squared_error / count)
        ),
        'mae': float(
            absolute_error / count
        ),
        'cosine_baseline_rmse': float(
            np.sqrt(
                baseline_squared_error / count
            )
        ),
    }


def log_input_artifacts(metadata_path):
    """Record input hashes and source files for traceability."""
    data_files = [
        'users_train.csv',
        'users_val.csv',
        'users_test.csv',
        'movies.csv',
        'metadata.json',
    ]

    manifest = {
        name: file_sha256(
            TRAINING_DATA_DIR / name
        )
        for name in data_files
    }

    with tempfile.TemporaryDirectory() as temporary_dir:
        manifest_path = (
            Path(temporary_dir)
            / 'data_manifest.json'
        )

        manifest_path.write_text(
            json.dumps(manifest, indent=2),
            encoding='utf-8',
        )

        mlflow.log_artifact(
            str(manifest_path),
            artifact_path='data',
        )

    mlflow.log_artifact(
        str(metadata_path),
        artifact_path='data',
    )

    mlflow.log_artifact(
        str(Path(__file__).resolve()),
        artifact_path='source',
    )

    mlflow.log_artifact(
        str(PROJECT_ROOT / 'src' / 'config.py'),
        artifact_path='source',
    )


def main():
    validate_config()

    torch.manual_seed(SEED)
    np.random.seed(SEED)

    metadata_path = (
        TRAINING_DATA_DIR / 'metadata.json'
    )

    metadata = json.loads(
        metadata_path.read_text(
            encoding='utf-8'
        )
    )

    genres = metadata['genres']

    if not genres or len(set(genres)) != len(genres):
        raise ValueError(
            'Metadata must contain unique genre features'
        )

    user_ids = {}
    user_features = {}

    for split in ('train', 'val', 'test'):
        ids, features = load_features(
            TRAINING_DATA_DIR
            / f'users_{split}.csv',
            'userId',
            genres,
        )

        user_ids[split] = ids
        user_features[split] = features

    # Users must not overlap across splits.
    for left, right in (
        ('train', 'val'),
        ('train', 'test'),
        ('val', 'test'),
    ):
        if (
            set(user_ids[left])
            & set(user_ids[right])
        ):
            raise ValueError(
                f'User overlap: {left} and {right}'
            )

    _, movies = load_features(
        TRAINING_DATA_DIR / 'movies.csv',
        'movieId',
        genres,
    )

    model = TwoTower(
        input_dim=len(genres),
        hidden_dim=HIDDEN_DIM,
        embedding_dim=EMBEDDING_DIM,
    )

    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=LEARNING_RATE,
    )

    mlflow.set_tracking_uri(
        MLFLOW_TRACKING_URI
    )
    mlflow.set_registry_uri(
        MLFLOW_TRACKING_URI
    )
    mlflow.set_experiment(
        MLFLOW_EXPERIMENT_NAME
    )

    training_config = {
        'seed': SEED,
        'batch_size': BATCH_SIZE,
        'pairs_per_user': PAIRS_PER_USER,
        'eval_pairs_per_user': EVAL_PAIRS_PER_USER,
        'epochs': EPOCHS,
        'learning_rate': LEARNING_RATE,
        'hidden_dim': HIDDEN_DIM,
        'embedding_dim': EMBEDDING_DIM,
        'input_dim': len(genres),
        'n_train_users': len(user_features['train']),
        'n_val_users': len(user_features['val']),
        'n_test_users': len(user_features['test']),
        'n_movies': len(movies),
        'loss': 'mse',
        'label': 'genre_cosine',
        'pair_sampling': 'uniform_movies_with_replacement',
        'device': 'cpu',
        'val_seed_offset': VAL_SEED_OFFSET,
        'test_seed_offset': TEST_SEED_OFFSET,
        'registered_model_name': (
            MLFLOW_REGISTERED_MODEL_NAME
        ),
        'serialization_format': (
            MLFLOW_SERIALIZATION_FORMAT
        ),
    }

    with mlflow.start_run(
        run_name=MLFLOW_RUN_NAME,
    ) as run:
        mlflow.log_params(training_config)

        mlflow.set_tags({
            'task': 'genre_similarity_approximation',
            'uses_ratings': 'false',
            'evaluation': 'held_out_users_sampled_pairs',
            'registration_status': 'pending',
        })

        log_input_artifacts(metadata_path)

        best_val_rmse = float('inf')
        best_state = None
        best_epoch = None

        train_users = user_features['train']

        total_pairs = (
            len(train_users)
            * PAIRS_PER_USER
        )

        for epoch in range(1, EPOCHS + 1):
            model.train()

            # Sample new movies each epoch.
            generator = (
                torch.Generator()
                .manual_seed(SEED + epoch)
            )

            user_order = torch.randperm(
                len(train_users),
                generator=generator,
            )

            squared_error = 0.0
            count = 0

            for start in range(
                0,
                total_pairs,
                BATCH_SIZE,
            ):
                stop = min(
                    start + BATCH_SIZE,
                    total_pairs,
                )

                positions = (
                    torch.arange(start, stop)
                    // PAIRS_PER_USER
                )

                batch_user_indices = (
                    user_order[positions]
                )

                batch_movie_indices = torch.randint(
                    len(movies),
                    (stop - start,),
                    generator=generator,
                )

                batch_users = train_users[
                    batch_user_indices
                ]

                batch_movies = movies[
                    batch_movie_indices
                ]

                # These are synthetic genre labels,
                # not observed ratings.
                targets = (
                    batch_users * batch_movies
                ).sum(dim=1)

                optimizer.zero_grad(
                    set_to_none=True
                )

                predictions = model(
                    batch_users,
                    batch_movies,
                )

                loss = F.mse_loss(
                    predictions,
                    targets,
                )

                if not torch.isfinite(loss).item():
                    raise RuntimeError(
                        'Non-finite training loss '
                        f'at epoch {epoch}'
                    )

                loss.backward()
                optimizer.step()

                squared_error += (
                    (predictions.detach() - targets)
                    .square()
                    .sum()
                    .item()
                )

                count += len(targets)

            train_rmse = float(
                np.sqrt(
                    squared_error / count
                )
            )

            # Fixed validation sampling across epochs.
            val_metrics = evaluate(
                model,
                user_features['val'],
                movies,
                seed=(
                    SEED + VAL_SEED_OFFSET
                ),
            )

            mlflow.log_metrics({
                'train_rmse': train_rmse,
                'val_rmse': val_metrics['rmse'],
                'val_mae': val_metrics['mae'],
                'val_cosine_baseline_rmse': (
                    val_metrics[
                        'cosine_baseline_rmse'
                    ]
                ),
            }, step=epoch)

            print(
                f'Epoch {epoch:02d}/{EPOCHS} | '
                f'train RMSE={train_rmse:.5f} | '
                f'val RMSE={val_metrics["rmse"]:.5f}'
            )

            if val_metrics['rmse'] < best_val_rmse:
                best_val_rmse = (
                    val_metrics['rmse']
                )

                best_state = copy.deepcopy(
                    model.state_dict()
                )

                best_epoch = epoch

        if best_state is None or best_epoch is None:
            raise RuntimeError(
                'No valid checkpoint selected; '
                'check validation loss.'
            )

        # Restore the best validation checkpoint.
        model.load_state_dict(best_state)
        model.eval()

        # Evaluate test only after model selection.
        test_metrics = evaluate(
            model,
            user_features['test'],
            movies,
            seed=(
                SEED + TEST_SEED_OFFSET
            ),
        )

        mlflow.log_metrics({
            'best_epoch': float(best_epoch),
            'best_val_rmse': best_val_rmse,
            'test_rmse': test_metrics['rmse'],
            'test_mae': test_metrics['mae'],
            'test_cosine_baseline_rmse': (
                test_metrics[
                    'cosine_baseline_rmse'
                ]
            ),
        })

        output_dir = (
            MODELS_DIR
            / 'two_tower'
            / run.info.run_id
        )

        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        checkpoint_path = (
            output_dir / 'checkpoint.pt'
        )

        torch.save({
            'model_state_dict': (
                model.state_dict()
            ),
            'input_dim': len(genres),
            'hidden_dim': HIDDEN_DIM,
            'embedding_dim': EMBEDDING_DIM,
            'genres': genres,
            'input_normalization': 'row_l2',
            'config': training_config,
            'best_epoch': best_epoch,
            'label_type': 'genre_cosine_pseudo_label',
        }, checkpoint_path)

        metrics_path = (
            output_dir / 'metrics.json'
        )

        metrics_path.write_text(
            json.dumps({
                'best_epoch': best_epoch,
                'best_val_rmse': best_val_rmse,
                'test': test_metrics,
            }, indent=2),
            encoding='utf-8',
        )

        # Persist training outputs before registration.
        mlflow.log_artifacts(
            str(output_dir),
            artifact_path='training',
        )

        print(f'Best epoch: {best_epoch}')
        print(
            f'Test RMSE: '
            f'{test_metrics["rmse"]:.5f}'
        )
        print(
            f'Test MAE: '
            f'{test_metrics["mae"]:.5f}'
        )
        print(
            f'MLflow run ID: '
            f'{run.info.run_id}'
        )
        print(
            f'Checkpoint: {checkpoint_path}'
        )

        mlflow.set_tag(
            'training_status',
            'completed',
        )

        # Register the selected model.
        try:
            model_info = mlflow_pytorch.log_model(
                pytorch_model=model,
                name='model',
                serialization_format=(
                    MLFLOW_SERIALIZATION_FORMAT
                ),
                code_paths=[
                    str(PROJECT_ROOT / 'src'),
                ],
                registered_model_name=(
                    MLFLOW_REGISTERED_MODEL_NAME
                ),
                metadata={
                    'source_training_run_id': (
                        run.info.run_id
                    ),
                    'genres': genres,
                    'input_normalization': 'row_l2',
                    'label_type': (
                        'genre_cosine_pseudo_label'
                    ),
                },
            )

            registered_version = (
                model_info.registered_model_version
            )

            if registered_version is None:
                raise RuntimeError(
                    'Model was logged, but no registered '
                    'model version was returned.'
                )

        except Exception:
            mlflow.set_tag(
                'registration_status',
                'failed',
            )

            print(
                'Training outputs were saved, '
                'but model registration failed. '
                'The saved checkpoint can be registered '
                'without retraining.'
            )

            raise

        registry_uri = (
            f'models:/{MLFLOW_REGISTERED_MODEL_NAME}'
            f'/{registered_version}'
        )

        registration_info = {
            'model_name': (
                MLFLOW_REGISTERED_MODEL_NAME
            ),
            'model_version': str(
                registered_version
            ),
            'model_uri': model_info.model_uri,
            'registry_uri': registry_uri,
            'source_training_run_id': (
                run.info.run_id
            ),
        }

        registration_path = (
            output_dir / 'registration.json'
        )

        registration_path.write_text(
            json.dumps(
                registration_info,
                indent=2,
            ),
            encoding='utf-8',
        )

        mlflow.log_artifact(
            str(registration_path),
            artifact_path='training',
        )

        mlflow.set_tags({
            'registration_status': 'completed',
            'registered_model_name': (
                MLFLOW_REGISTERED_MODEL_NAME
            ),
            'registered_model_version': str(
                registered_version
            ),
        })

        print(
            f'Model URI: '
            f'{model_info.model_uri}'
        )
        print(
            f'Registered model: '
            f'{MLFLOW_REGISTERED_MODEL_NAME}'
        )
        print(
            f'Registered model version: '
            f'{registered_version}'
        )
        print(
            f'Registry URI: {registry_uri}'
        )


if __name__ == '__main__':
    main()