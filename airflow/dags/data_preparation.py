"""Manually run the existing preparation image through the host Docker Engine."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

from airflow.providers.docker.operators.docker import DockerOperator
from airflow.sdk import DAG
from docker.types import Mount

# These are daemon-side paths. /opt/airflow is the scheduler's filesystem and
# cannot be used as a bind source for a sibling container on Docker Desktop.
project = PurePosixPath(os.environ['AIRFLOW_DOCKER_PROJECT_DIR'])

with DAG(
    dag_id='data_preparation',
    description='Build and validate local feature matrices using a separate container.',
    start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    dagrun_timeout=timedelta(minutes=15),
    tags=['data-preparation', 'movie-reco'],
) as dag:
    prepare_features = DockerOperator(
        task_id='prepare_features',
        image='movie-reco-data-preparation:local',
        docker_url='unix://var/run/docker.sock',
        api_version='auto',
        force_pull=False,
        # Keep the image entrypoint; no argument means read params.yaml.
        mount_tmp_dir=False,
        mounts=[
            Mount(
                '/app/data/raw', str(project / 'data/raw'), type='bind', read_only=True
            ),
            Mount(
                '/app/data/interim/ratings_parts',
                str(project / 'data/interim/ratings_parts'),
                type='bind',
                read_only=True,
            ),
            Mount(
                '/app/params.yaml',
                str(project / 'params.yaml'),
                type='bind',
                read_only=True,
            ),
            Mount('/app/data/processed', str(project / 'data/processed'), type='bind'),
        ],
        network_mode='none',
        auto_remove='force',
        do_xcom_push=False,
        retries=0,
        execution_timeout=timedelta(minutes=10),
        labels={
            'project': 'movie-reco',
            'managed_by': 'airflow',
            'job': 'data_preparation',
        },
    )
