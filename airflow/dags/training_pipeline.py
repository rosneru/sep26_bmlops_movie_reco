"""Manually prepare features, then train/register KNN through Docker containers."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

from airflow.exceptions import AirflowException
from airflow.providers.docker.operators.docker import DockerOperator
from airflow.sdk import DAG
from airflow.sdk.log import mask_secret
from docker.types import Mount

# These are daemon-side paths. /opt/airflow is the scheduler's filesystem and
# cannot be used as a bind source for a sibling container on Docker Desktop.
project = PurePosixPath(os.environ['AIRFLOW_DOCKER_PROJECT_DIR'])


class MLflowTrainingOperator(DockerOperator):
    """Resolve credentials in the task process, never during DAG serialization."""

    def execute(self, context):
        credentials = {
            name: os.environ.get(name, '')
            for name in (
                'MLFLOW_TRACKING_URI',
                'MLFLOW_TRACKING_USERNAME',
                'MLFLOW_TRACKING_PASSWORD',
            )
        }
        missing = [name for name, value in credentials.items() if not value.strip()]
        if missing:
            raise AirflowException(
                'Missing scheduler MLflow settings: '
                + ', '.join(missing)
                + '. Set MLFLOW_TRACKING_USERNAME and DAGSHUB_TOKEN in .env, '
                'then recreate airflow-scheduler.'
            )
        mask_secret(credentials['MLFLOW_TRACKING_PASSWORD'])
        self._private_environment.update(credentials)
        return super().execute(context)


with DAG(
    dag_id='training_pipeline',
    description='Prepare feature matrices, then train and register KNN in MLflow.',
    start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    dagrun_timeout=timedelta(minutes=45),
    tags=['data-preparation', 'knn', 'training', 'movie-reco'],
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

    train_knn = MLflowTrainingOperator(
        task_id='train_knn',
        image='movie-reco-train:knn',
        docker_url='unix://var/run/docker.sock',
        api_version='auto',
        force_pull=False,
        environment={'MODEL_TYPE': 'knn'},
        mounts=[
            Mount(
                '/app/data/processed',
                str(project / 'data/processed'),
                type='bind',
                read_only=True,
            ),
        ],
        # Outbound HTTPS is needed for DagsHub tracking and model registration.
        network_mode='bridge',
        mount_tmp_dir=False,
        auto_remove='force',
        do_xcom_push=False,
        # Retrying after partial registration could create another model version.
        retries=0,
        execution_timeout=timedelta(minutes=30),
        labels={'project': 'movie-reco', 'managed_by': 'airflow', 'job': 'train_knn'},
    )

    prepare_features >> train_knn
