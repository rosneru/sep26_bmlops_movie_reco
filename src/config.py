import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = PROJECT_ROOT / 'data' / 'raw'
INTERIM_DATA_DIR = PROJECT_ROOT / 'data' / 'interim'
RATINGS_PARTS_DIR = INTERIM_DATA_DIR / 'ratings_parts'
RATINGS_PART_FILENAME = 'ratings_{:02d}.csv'
PROCESSED_DATA_DIR = PROJECT_ROOT / 'data' / 'processed'
USER_MATRIX_PATH = PROCESSED_DATA_DIR / 'user_matrix.csv'
MOVIE_MATRIX_PATH = PROCESSED_DATA_DIR / 'movie_matrix.csv'
MODELS_DIR = PROJECT_ROOT / 'models'
MODEL_PATH = MODELS_DIR / 'model.pkl'

N_RECOMMENDATIONS = 10

# Model
TRAINING_DATA_DIR = PROCESSED_DATA_DIR / 'two_tower'
RANDOM_SEED = 42
MISSING_GENRE = '(no genres listed)'

# Two-Tower training (CPU)
BATCH_SIZE = 256
PAIRS_PER_USER = 20
EVAL_PAIRS_PER_USER = 20
EPOCHS = 10
LEARNING_RATE = 0.001
HIDDEN_DIM = 64
EMBEDDING_DIM = 32


TRAIN_RATIO = 0.80
VAL_RATIO = 0.10
TEST_RATIO = 0.10

# Fixed evaluation sampling seeds relative to RANDOM_SEED
VAL_SEED_OFFSET = 1000
TEST_SEED_OFFSET = 2000

# MLflow
MLFLOW_TRACKING_URI = os.getenv(
    'MLFLOW_TRACKING_URI',
    'http://localhost:5000',
)
MLFLOW_EXPERIMENT_NAME = 'movie-genre-two-tower'
MLFLOW_RUN_NAME = 'two-tower-genre-cosine'
MLFLOW_REGISTERED_MODEL_NAME = 'movie-genre-two-tower'

MLFLOW_SERIALIZATION_FORMAT = 'pickle'
