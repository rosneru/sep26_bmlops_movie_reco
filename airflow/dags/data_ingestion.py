"""Upload the next rating part to the DagsHub bucket daily, to simulate arriving data."""

import logging
import os
from datetime import timedelta

import requests
from airflow.exceptions import AirflowException
from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG
from airflow.sdk.exceptions import AirflowSkipException
from airflow.sdk.log import mask_secret
from airflow.timetables.trigger import CronTriggerTimetable
from rating_assets import RATING_PARTS

logger = logging.getLogger(__name__)

# Compose service name; the scheduler is in the same Compose network.
DATA_COLLECTION_URL = 'http://data_collection:8001'


def ingest_next_part():
    """Ask the data collection service to upload the next rating part."""
    username = os.environ.get('DATA_COLLECTION_USERNAME', '')
    password = os.environ.get('DATA_COLLECTION_PASSWORD', '')
    if not (username.strip() and password.strip()):
        raise AirflowException(
            'Set DATA_COLLECTION_USERNAME and DATA_COLLECTION_PASSWORD in .env, '
            'then recreate airflow-scheduler.'
        )
    mask_secret(password)

    try:
        login = requests.post(
            f'{DATA_COLLECTION_URL}/token',
            data={'username': username, 'password': password},
            timeout=15,
        )
    except requests.ConnectionError as error:
        raise AirflowException(
            f'Data collection service not reachable at {DATA_COLLECTION_URL}. '
            'Start it with: docker compose up -d data_collection'
        ) from error
    if not login.ok:
        raise AirflowException(
            f'Login at the data collection service failed with HTTP {login.status_code}'
        )
    token = login.json()['access_token']
    mask_secret(token)

    # Uploading a part of ~60 MB can take a while
    response = requests.post(
        f'{DATA_COLLECTION_URL}/ingest',
        json={'next_part': True},
        headers={'Authorization': f'Bearer {token}'},
        timeout=600,
    )
    if not response.ok:
        raise AirflowException(
            f'Ingest failed with HTTP {response.status_code}: {response.text}'
        )
    result = response.json()
    logger.info('Ingest result: %s', result)

    # A skipped task emits no asset event, so consumers are not triggered
    if result['status'] != 'ingested':
        raise AirflowSkipException(result.get('detail') or result['status'])
    return result


with DAG(
    dag_id='data_ingestion',
    description='Upload the next rating part to the DagsHub bucket.',
    # A successful upload triggers the training pipeline through RATING_PARTS.
    schedule=CronTriggerTimetable(
        '0 9 * * *', timezone='Europe/Berlin', run_immediately=timedelta(0)
    ),
    catchup=False,
    max_active_runs=1,
    tags=['data-collection', 'movie-reco'],
) as dag:
    PythonOperator(
        task_id='ingest_next_part',
        python_callable=ingest_next_part,
        outlets=[RATING_PARTS],
        # No retry: if the upload succeeded but the response was lost, a retry
        # would upload one more part.
        retries=0,
        execution_timeout=timedelta(minutes=20),
    )
