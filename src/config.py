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
MODEL_TYPE = os.getenv("MODEL_TYPE", "knn").strip().lower()

KNN_NEIGHBORS = 20
KNN_ALGORITHM = 'ball_tree'

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

MODEL_NAMES = {
    'knn': {
        'experiment': 'movie-genre-knn',
        'run': 'knn-genre-neighbors',
        'registry': 'movie-genre-knn',
    },
    'two_tower': {
        'experiment': 'movie-genre-two-tower',
        'run': 'two-tower-genre-cosine',
        'registry': 'movie-genre-two-tower',
    },
}

if MODEL_TYPE not in MODEL_NAMES:
    raise ValueError(
        f"Unsupported MODEL_TYPE: {MODEL_TYPE}. "
        f"Choose one of: {', '.join(MODEL_NAMES)}"
    )

MLFLOW_EXPERIMENT_NAME = MODEL_NAMES[MODEL_TYPE]['experiment']
MLFLOW_RUN_NAME = MODEL_NAMES[MODEL_TYPE]['run']
MLFLOW_REGISTERED_MODEL_NAME = MODEL_NAMES[MODEL_TYPE]['registry']

MLFLOW_SERIALIZATION_FORMAT = 'pickle'
