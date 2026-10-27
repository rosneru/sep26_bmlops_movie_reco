"""Evaluate genre-cosine pseudo-label approximation, not recommendation quality."""

import numpy as np
import torch
from torch.nn import functional as F

from src.config import BATCH_SIZE, EVAL_PAIRS_PER_USER


@torch.no_grad()
def evaluate(
    model,
    users,
    movies,
    seed,
    *,
    batch_size=BATCH_SIZE,
    pairs_per_user=EVAL_PAIRS_PER_USER,
):
    """Evaluate fixed sampled pairs against genre cosine targets."""
    model.eval()

    generator = torch.Generator().manual_seed(seed)

    squared_error = 0.0
    absolute_error = 0.0
    baseline_squared_error = 0.0
    count = 0

    total_pairs = len(users) * pairs_per_user

    for start in range(
        0,
        total_pairs,
        batch_size,
    ):
        stop = min(
            start + batch_size,
            total_pairs,
        )

        user_indices = torch.arange(start, stop) // pairs_per_user

        movie_indices = torch.randint(
            len(movies),
            (stop - start,),
            generator=generator,
        )

        batch_users = users[user_indices]
        batch_movies = movies[movie_indices]

        # Dot product equals cosine for normalized inputs.
        targets = (batch_users * batch_movies).sum(dim=1)

        predictions = model(
            batch_users,
            batch_movies,
        )

        if not torch.isfinite(predictions).all().item():
            raise RuntimeError('Non-finite predictions during evaluation')

        errors = predictions - targets

        squared_error += errors.square().sum().item()
        absolute_error += errors.abs().sum().item()

        baseline_predictions = F.cosine_similarity(
            batch_users,
            batch_movies,
            dim=1,
        )

        baseline_squared_error += (baseline_predictions - targets).square().sum().item()

        count += len(targets)

    if count == 0:
        raise ValueError('No evaluation pairs available')

    return {
        'rmse': float(np.sqrt(squared_error / count)),
        'mae': float(absolute_error / count),
        'cosine_baseline_rmse': float(np.sqrt(baseline_squared_error / count)),
    }
