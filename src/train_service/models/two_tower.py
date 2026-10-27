"""Two-tower network and fitting; no MLflow, HTTP, or artifact storage."""

import copy
import json

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from src.train_service.prepare_data import prepare_data
from src.train_service.evaluate import evaluate


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

        return (user_embeddings * movie_embeddings).sum(dim=1)


def fit(
    model,
    train_users,
    validation_users,
    movies,
    *,
    epochs,
    batch_size,
    pairs_per_user,
    eval_pairs_per_user,
    learning_rate,
    seed,
    validation_seed_offset,
    on_epoch=None,
):
    """Fit the supplied two-tower model and restore its best validation epoch.

    Sampling, loss, optimizer, and checkpoint selection match Mani's implementation.
    on_epoch(epoch, metrics) lets the entry point log without an MLflow dependency here.
    """
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    best_val_rmse = float('inf')
    best_state = None
    best_epoch = None

    total_pairs = len(train_users) * pairs_per_user

    for epoch in range(1, epochs + 1):
        model.train()

        # Sample new movies each epoch.
        generator = torch.Generator().manual_seed(seed + epoch)

        user_order = torch.randperm(
            len(train_users),
            generator=generator,
        )

        squared_error = 0.0
        count = 0

        for start in range(
            0,
            total_pairs,
            batch_size,
        ):
            stop = min(
                start + batch_size,
                total_pairs,
            )

            positions = torch.arange(start, stop) // pairs_per_user

            batch_user_indices = user_order[positions]

            batch_movie_indices = torch.randint(
                len(movies),
                (stop - start,),
                generator=generator,
            )

            batch_users = train_users[batch_user_indices]

            batch_movies = movies[batch_movie_indices]

            # These are synthetic genre labels,
            # not observed ratings.
            targets = (batch_users * batch_movies).sum(dim=1)

            optimizer.zero_grad(set_to_none=True)

            predictions = model(
                batch_users,
                batch_movies,
            )

            loss = F.mse_loss(
                predictions,
                targets,
            )

            if not torch.isfinite(loss).item():
                raise RuntimeError(f'Non-finite training loss at epoch {epoch}')

            loss.backward()
            optimizer.step()

            squared_error += (predictions.detach() - targets).square().sum().item()

            count += len(targets)

        train_rmse = float(np.sqrt(squared_error / count))

        # Fixed validation sampling across epochs.
        val_metrics = evaluate(
            model,
            validation_users,
            movies,
            seed=seed + validation_seed_offset,
            batch_size=batch_size,
            pairs_per_user=eval_pairs_per_user,
        )

        epoch_metrics = {
            'train_rmse': train_rmse,
            'val_rmse': val_metrics['rmse'],
            'val_mae': val_metrics['mae'],
            'val_cosine_baseline_rmse': (val_metrics['cosine_baseline_rmse']),
        }
        if on_epoch is not None:
            on_epoch(epoch, epoch_metrics)

        print(
            f'Epoch {epoch:02d}/{epochs} | '
            f'train RMSE={train_rmse:.5f} | '
            f'val RMSE={val_metrics["rmse"]:.5f}'
        )

        if val_metrics['rmse'] < best_val_rmse:
            best_val_rmse = val_metrics['rmse']

            best_state = copy.deepcopy(model.state_dict())

            best_epoch = epoch

    if best_state is None or best_epoch is None:
        raise RuntimeError('No valid checkpoint selected; check validation loss.')

    # Restore the best validation checkpoint.
    model.load_state_dict(best_state)
    model.eval()

    return model, best_epoch, best_val_rmse


def resolve_settings(config):
    """Return validated settings used by this implementation, not guessed log values."""
    settings = {
        'seed': config.RANDOM_SEED,
        'epochs': config.EPOCHS,
        'batch_size': config.BATCH_SIZE,
        'pairs_per_user': config.PAIRS_PER_USER,
        'eval_pairs_per_user': config.EVAL_PAIRS_PER_USER,
        'learning_rate': config.LEARNING_RATE,
        'hidden_dim': config.HIDDEN_DIM,
        'embedding_dim': config.EMBEDDING_DIM,
        'val_seed_offset': config.VAL_SEED_OFFSET,
        'test_seed_offset': config.TEST_SEED_OFFSET,
        'registered_model_name': config.MLFLOW_REGISTERED_MODEL_NAME,
        'serialization_format': config.MLFLOW_SERIALIZATION_FORMAT,
    }
    for name in [
        'epochs',
        'batch_size',
        'pairs_per_user',
        'eval_pairs_per_user',
        'hidden_dim',
        'embedding_dim',
    ]:
        value = settings[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f'{name} must be a positive integer')
    if not np.isfinite(settings['learning_rate']) or settings['learning_rate'] <= 0:
        raise ValueError('learning_rate must be finite and positive')
    if settings['serialization_format'] != 'pickle':
        raise ValueError('This two-tower exporter currently supports pickle only')
    return settings


def load_data(directory):
    """Prepare the original feature matrices in memory for this training run."""
    data = prepare_data(directory / 'user_matrix.csv', directory / 'movie_matrix.csv')
    data['user_features'] = {
        name: torch.from_numpy(values)
        for name, values in data['user_features'].items()
    }
    data['movies'] = torch.from_numpy(data['movies'])
    return data


def parameters(settings, data):
    """Expose actual architecture/training settings to generic experiment tracking."""
    return {
        **settings,
        'model_type': 'two_tower',
        'input_dim': len(data['genres']),
        'n_train_users': len(data['user_features']['train']),
        'n_val_users': len(data['user_features']['val']),
        'n_test_users': len(data['user_features']['test']),
        'n_movies': len(data['movies']),
        'loss': 'mse',
        'label': 'genre_cosine',
        'pair_sampling': 'uniform_movies_with_replacement',
        'device': 'cpu',
    }


def run_tags():
    return {
        'task': 'genre_similarity_approximation',
        'label_type': 'genre_cosine_pseudo_label',
        'uses_ratings': 'false',
        'evaluation': 'held_out_users_sampled_pairs',
    }


def train(data, settings, on_epoch=None):
    """Own seeding, model construction, fitting and model-specific evaluation."""
    torch.manual_seed(settings['seed'])
    np.random.seed(settings['seed'])
    model = TwoTower(
        len(data['genres']), settings['hidden_dim'], settings['embedding_dim']
    )
    model, best_epoch, best_val_rmse = fit(
        model,
        data['user_features']['train'],
        data['user_features']['val'],
        data['movies'],
        epochs=settings['epochs'],
        batch_size=settings['batch_size'],
        pairs_per_user=settings['pairs_per_user'],
        eval_pairs_per_user=settings['eval_pairs_per_user'],
        learning_rate=settings['learning_rate'],
        seed=settings['seed'],
        validation_seed_offset=settings['val_seed_offset'],
        on_epoch=on_epoch,
    )
    # No test evaluation during checkpoint selection.
    test = evaluate(
        model,
        data['user_features']['test'],
        data['movies'],
        seed=settings['seed'] + settings['test_seed_offset'],
        batch_size=settings['batch_size'],
        pairs_per_user=settings['eval_pairs_per_user'],
    )
    return {
        'model': model,
        'best_epoch': best_epoch,
        'best_val_rmse': best_val_rmse,
        'test': test,
        'metrics': {
            'best_epoch': float(best_epoch),
            'best_val_rmse': best_val_rmse,
            'test_rmse': test['rmse'],
            'test_mae': test['mae'],
            'test_cosine_baseline_rmse': test['cosine_baseline_rmse'],
        },
    }


def registry_tags(data):
    return {
        'genres': json.dumps(data['genres'], ensure_ascii=False),
        'input_normalization': 'row_l2',
        'label_type': 'genre_cosine_pseudo_label',
    }


def export(
    result, data, resolved_parameters, model_dir, *, source_root, run_id
):
    """Package the model locally for upload to MLflow."""
    import mlflow.pytorch

    # mlflow.pytorch.save_model() below saves the model weights,
    # so we do not also save a separate checkpoint.pt.

    # Metrics are logged directly to the MLflow run in train_model.py;
    # a separate metrics.json file would duplicate them.

    # Flatten the shared and model-specific files so the exported environment
    # does not depend on a relative requirements-file include.
    requirements_dir = source_root / 'train_service'
    pip_requirements = (requirements_dir / 'requirements.txt').read_text().splitlines()
    pip_requirements += [
        line for line in
        (requirements_dir / 'requirements-two-tower.txt').read_text().splitlines()
        if not line.startswith('-r ')
    ]

    mlflow.pytorch.save_model(
        pytorch_model=result['model'],
        path=str(model_dir),
        serialization_format=resolved_parameters['serialization_format'],
        code_paths=[str(source_root)],
        pip_requirements=pip_requirements,
        metadata={
            'source_training_run_id': run_id,
            'training_parameters': resolved_parameters,
            'genres': data['genres'],
            'input_normalization': 'row_l2',
            'label_type': 'genre_cosine_pseudo_label',
        },
    )
