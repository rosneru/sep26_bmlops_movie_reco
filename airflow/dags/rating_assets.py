from airflow.sdk import Asset

RATING_PARTS = Asset(
    name='rating_parts',
    uri='dagshub-bucket://sep26_bmlops_movie_reco/ratings_parts',
)
