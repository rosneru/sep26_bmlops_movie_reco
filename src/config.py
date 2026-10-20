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
