import os
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import config

# Paths can be overridden via environment variables (e.g. inside a Docker
# container). The defaults from config.py point to the project directory.
MODEL_PATH = Path(os.getenv('MODEL_PATH', config.MODEL_PATH))
USER_MATRIX_PATH = Path(os.getenv('USER_MATRIX_PATH', config.USER_MATRIX_PATH))
MOVIE_MATRIX_PATH = Path(os.getenv('MOVIE_MATRIX_PATH', config.MOVIE_MATRIX_PATH))
from config import N_RECOMMENDATIONS


# Loading the trained model and the matrices once at startup
try:
    with open(MODEL_PATH, 'rb') as f:
        model = pickle.load(f)

    # Genre profile of each user, indexed by userId
    user_matrix = pd.read_csv(USER_MATRIX_PATH, index_col='userId')

    # kneighbors() returns row positions in the movie matrix the model was
    # trained on. This array maps those positions back to movieIds.
    movie_ids = pd.read_csv(MOVIE_MATRIX_PATH, usecols=['movieId'])[
        'movieId'
    ].to_numpy()
except FileNotFoundError as e:
    raise RuntimeError(f'Required file not found: {e.filename}') from e

app = FastAPI(
    title='Movie Recommendation API',
    description='Recommends movies to users based on their genre preferences.',
    version='0.1.0',
)


# data model for input query
class PredictRequest(BaseModel):
    user_ids: list[int] = Field(min_length=1)
    seed: int | None = Field(
        default=None,
        ge=0,
        description='Makes the recommendations reproducible. Without a seed, '
        'they vary from call to call.',
    )

    model_config = {
        'json_schema_extra': {
            'examples': [
                {
                    'user_ids': [1, 2, 3],
                }
            ]
        }
    }


# prediction endpoint
@app.post('/predict')
def predict(request: PredictRequest):
    unknown_ids = [i for i in request.user_ids if i not in user_matrix.index]
    if unknown_ids:
        raise HTTPException(status_code=404, detail=f'Unknown user ids: {unknown_ids}')

    users = user_matrix.loc[request.user_ids]
    _, indices = model.kneighbors(users)

    recommendations = []
    for user_id, row in zip(request.user_ids, indices):
        # Many movies share the same genres and thus have the same distance,
        # so choose randomly among the nearest neighbors. Seeding with
        # (seed, user_id) makes the result of each user reproducible,
        # independent of the other user ids in the request.
        rng = np.random.default_rng(
            None if request.seed is None else [request.seed, user_id]
        )
        selection = rng.choice(row, size=N_RECOMMENDATIONS, replace=False)
        recommendations.append(
            {'user_id': user_id, 'movie_ids': movie_ids[selection].tolist()}
        )

    return {'recommendations': recommendations}
