
import pandas as pd
from sklearn.neighbors import NearestNeighbors
import pickle


def train_model(movie_matrix):
    nbrs = NearestNeighbors(n_neighbors=20, algorithm='ball_tree').fit(
        movie_matrix.drop('movieId', axis=1)
    )
    return nbrs

if __name__ == '__main__':
    movie_matrix = pd.read_csv('data/processed/movie_matrix.csv')
    model = train_model(movie_matrix)
    filehandler = open('models/model.pkl', 'wb')
    pickle.dump(model, filehandler)
    filehandler.close()


"""
import logging
import os

import mlflow
import mlflow.pytorch
import numpy as np
import pandas as pd
import torch

from pathlib import Path
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

logger = logging.getLogger(__name__)

# Configuration
RATINGS_PATH = Path(os.getenv("RATINGS_PATH", "data/ratings.csv"))
MLFLOW_TRACKING_URI = os.getenv(
    "MLFLOW_TRACKING_URI", "http://localhost:5000"
)

EXPERIMENT_NAME = "movie-recommendation-training"
REGISTERED_MODEL_NAME = "movie-recommender"

EMBEDDING_DIM = 32
EPOCHS = 20
BATCH_SIZE = 256
LEARNING_RATE = 0.001
RANDOM_SEED = 42


class MatrixFactorization(nn.Module):
    def __init__(self, n_users, n_movies, embedding_dim):
        super().__init__()

        self.user_embedding = nn.Embedding(n_users, embedding_dim)
        self.movie_embedding = nn.Embedding(n_movies, embedding_dim)

        self.user_bias = nn.Embedding(n_users, 1)
        self.movie_bias = nn.Embedding(n_movies, 1)

        self.global_bias = nn.Parameter(torch.zeros(1))

        nn.init.normal_(self.user_embedding.weight, std=0.05)
        nn.init.normal_(self.movie_embedding.weight, std=0.05)
        nn.init.zeros_(self.user_bias.weight)
        nn.init.zeros_(self.movie_bias.weight)

    def forward(self, user_ids, movie_ids):
        user_vectors = self.user_embedding(user_ids)
        movie_vectors = self.movie_embedding(movie_ids)

        interaction = (user_vectors * movie_vectors).sum(dim=1)

        return (
            interaction
            + self.user_bias(user_ids).squeeze(-1)
            + self.movie_bias(movie_ids).squeeze(-1)
            + self.global_bias
        )


def main():
    torch.manual_seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)

    # 1. Load and validate ratings
    ratings = pd.read_csv(RATINGS_PATH)

    required = {"userId", "movieId", "rating"}
    if not required.issubset(ratings.columns):
        raise ValueError(f"Missing columns: {required - set(ratings.columns)}")

    if ratings.empty:
        raise ValueError("Ratings dataset is empty.")

    if ratings[["userId", "movieId", "rating"]].isna().any().any():
        raise ValueError("Ratings contain missing values.")

    ratings["rating"] = pd.to_numeric(ratings["rating"], errors="raise")

    if not np.isfinite(ratings["rating"]).all():
        raise ValueError("Ratings contain infinite values.")

    # 2. Encode user and movie IDs
    user_codes, unique_users = pd.factorize(ratings["userId"], sort=True)
    movie_codes, unique_movies = pd.factorize(ratings["movieId"], sort=True)

    n_users = len(unique_users)
    n_movies = len(unique_movies)

    users = torch.tensor(user_codes, dtype=torch.long)
    movies = torch.tensor(movie_codes, dtype=torch.long)
    targets = torch.tensor(ratings["rating"].to_numpy(), dtype=torch.float32)

    # 3. Train/validation split
    generator = torch.Generator().manual_seed(RANDOM_SEED)
    indices = torch.randperm(len(ratings), generator=generator)

    split = int(0.8 * len(indices))
    if split == 0 or split == len(indices):
        raise ValueError("Not enough ratings for train/validation split.")

    train_idx = indices[:split]
    val_idx = indices[split:]

    train_data = TensorDataset(
        users[train_idx], movies[train_idx], targets[train_idx]
    )
    val_data = TensorDataset(
        users[val_idx], movies[val_idx], targets[val_idx]
    )

    train_loader = DataLoader(
        train_data, batch_size=BATCH_SIZE, shuffle=True
    )
    val_loader = DataLoader(
        val_data, batch_size=BATCH_SIZE, shuffle=False
    )

    # 4. Initialize model
    model = MatrixFactorization(n_users, n_movies, EMBEDDING_DIM)

    optimizer = torch.optim.Adam(
        model.parameters(), lr=LEARNING_RATE
    )
    criterion = nn.MSELoss()

    # 5. Configure MLflow
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT_NAME)

    with mlflow.start_run(run_name="matrix-factorization-training"):

        mlflow.log_params({
            "algorithm": "matrix_factorization",
            "embedding_dim": EMBEDDING_DIM,
            "epochs": EPOCHS,
            "batch_size": BATCH_SIZE,
            "learning_rate": LEARNING_RATE,
            "n_users": n_users,
            "n_movies": n_movies,
        })

        best_rmse = float("inf")
        best_state = None

        # 6. Training loop
        for epoch in range(EPOCHS):
            model.train()
            train_squared_error = 0.0
            train_count = 0

            for batch_users, batch_movies, batch_ratings in train_loader:
                optimizer.zero_grad()

                predictions = model(batch_users, batch_movies)
                loss = criterion(predictions, batch_ratings)

                loss.backward()
                optimizer.step()

                train_squared_error += (
                    (predictions.detach() - batch_ratings).square().sum().item()
                )
                train_count += len(batch_ratings)

            train_rmse = np.sqrt(train_squared_error / train_count)

            # 7. Validation
            model.eval()
            val_squared_error = 0.0
            val_absolute_error = 0.0
            val_count = 0

            with torch.no_grad():
                for batch_users, batch_movies, batch_ratings in val_loader:
                    predictions = model(batch_users, batch_movies)
                    errors = predictions - batch_ratings

                    val_squared_error += errors.square().sum().item()
                    val_absolute_error += errors.abs().sum().item()
                    val_count += len(batch_ratings)

            val_rmse = np.sqrt(val_squared_error / val_count)
            val_mae = val_absolute_error / val_count

            mlflow.log_metrics({
                "train_rmse": float(train_rmse),
                "val_rmse": float(val_rmse),
                "val_mae": float(val_mae),
            }, step=epoch + 1)

            logger.info(
                "Epoch %d/%d | Train RMSE: %.4f | Val RMSE: %.4f | Val MAE: %.4f",
                epoch + 1, EPOCHS, train_rmse, val_rmse, val_mae
            )

            if val_rmse < best_rmse:
                best_rmse = val_rmse
                best_state = {
                    key: value.detach().clone()
                    for key, value in model.state_dict().items()
                }

        # 8. Restore best model
        model.load_state_dict(best_state)
        model.eval()

        mlflow.log_metric("best_val_rmse", float(best_rmse))

        # 9. Save ID mappings as artifacts
        mapping_dir = Path("training_artifacts")
        mapping_dir.mkdir(exist_ok=True)

        pd.DataFrame({
            "userId": unique_users,
            "user_index": range(n_users)
        }).to_csv(mapping_dir / "user_mapping.csv", index=False)

        pd.DataFrame({
            "movieId": unique_movies,
            "movie_index": range(n_movies)
        }).to_csv(mapping_dir / "movie_mapping.csv", index=False)

        mlflow.log_artifacts(str(mapping_dir), artifact_path="mappings")

        # 10. Register trained model
        model_info = mlflow.pytorch.log_model(
            pytorch_model=model,
            name="model",
            registered_model_name=REGISTERED_MODEL_NAME,
        )

        logger.info("Best validation RMSE: %.4f", best_rmse)
        logger.info("Registered model URI: %s", model_info.model_uri)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
"""