import os
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field

from predict_service.model_loader import load_registered_model
from user_authentication_service.auth import require_predict_access
from user_authentication_service.auth import router as auth_router

USER_MATRIX_PATH = Path(__file__).resolve().parents[2] / 'data' / 'processed' / 'user_matrix.csv'
N_RECOMMENDATIONS = 10
CANDIDATE_COUNT = 20

recommender = load_registered_model()
user_matrix = pd.read_csv(
    Path(os.getenv('USER_MATRIX_PATH', USER_MATRIX_PATH)), index_col='userId'
)
if user_matrix.index.has_duplicates or user_matrix.index.isna().any():
    raise ValueError('User matrix has missing or duplicate IDs')
missing_genres = set(recommender.genres) - set(user_matrix.columns)
if missing_genres:
    raise ValueError(f'User matrix lacks model genres: {sorted(missing_genres)}')
if len(recommender.movie_ids) < N_RECOMMENDATIONS:
    raise ValueError('Model catalog is too small for the requested recommendations')

app = FastAPI(
    title='Movie Recommendation API',
    description='Recommends movies to users based on their genre preferences.',
    version='0.1.0',
)
app.include_router(auth_router)

PREDICTION_REQUESTS = Counter(
    'prediction_requests_total',
    'Number of prediction requests by HTTP status.',
    ['status'],
)


PREDICTION_HANDLER_REQUESTS = Counter(
    'prediction_handler_requests_total',
    'Number of requests that reached the prediction handler.',
)

PREDICTION_REQUEST_DURATION = Histogram(
    'prediction_request_duration_seconds',
    'Time spent handling POST /predict requests.',
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
@app.post('/predict', dependencies=[Depends(require_predict_access)])
def predict(request: PredictRequest):
    PREDICTION_HANDLER_REQUESTS.inc()
    unknown_ids = [i for i in request.user_ids if i not in user_matrix.index]
    if unknown_ids:
        raise HTTPException(status_code=404, detail=f'Unknown user ids: {unknown_ids}')

    users = user_matrix.loc[request.user_ids]
    try:
        indices = recommender.candidates(
            users, min(CANDIDATE_COUNT, len(recommender.movie_ids))
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

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
            {'user_id': user_id, 'movie_ids': recommender.movie_ids[selection].tolist()}
        )

    return {'recommendations': recommendations}


@app.get('/model', dependencies=[Depends(require_predict_access)])
def model_info():
    """Report the immutable registry selection loaded by this replica."""
    return {'model_uri': recommender.uri, 'model_type': recommender.model_type}


@app.get('/metrics', include_in_schema=False)
def metrics():
    return Response(
        content=generate_latest(),
        headers={'Content-Type': CONTENT_TYPE_LATEST},
    )


@app.middleware('http')
async def count_prediction_requests(request: Request, call_next):
    if request.method != 'POST' or request.url.path != '/predict':
        return await call_next(request)

    started = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        PREDICTION_REQUESTS.labels(status='500').inc()
        raise
    finally:
        PREDICTION_REQUEST_DURATION.observe(perf_counter() - started)

    PREDICTION_REQUESTS.labels(status=str(response.status_code)).inc()
    return response
