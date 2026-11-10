"""Prepare, train and deploy after new bucket data arrives or on manual trigger."""

import json
import os
from datetime import timedelta
from pathlib import PurePosixPath

from airflow.exceptions import AirflowException
from airflow.providers.docker.operators.docker import DockerOperator
from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG
from airflow.sdk.log import mask_secret
from docker.types import Mount
from prediction_deployment import deploy_prediction
from rating_assets import RATING_PARTS

# These are daemon-side paths. /opt/airflow is the scheduler's filesystem and
# cannot be used as a bind source for a sibling container on Docker Desktop.
project = PurePosixPath(os.environ['AIRFLOW_DOCKER_PROJECT_DIR'])


class BucketPreparationOperator(DockerOperator):
    """
    Pass the DagsHub bucket settings privately to the preparation container.

    Only execute() is overridden: it reads the settings from the scheduler
    environment when the task runs (never during DAG serialization), masks the
    token in the logs and adds them to the private environment, which is not
    rendered in the UI. Image, mounts, networking, logs and cleanup are left to
    DockerOperator.
    """

    def execute(self, context):
        settings = {
            name: os.environ.get(name, '')
            for name in ('DAGSHUB_S3_ENDPOINT_URL', 'DAGSHUB_BUCKET', 'DAGSHUB_TOKEN')
        }
        missing = [name for name, value in settings.items() if not value.strip()]
        if missing:
            raise AirflowException(
                'Missing scheduler bucket settings: '
                + ', '.join(missing)
                + '. Set them in .env, then recreate airflow-scheduler.'
            )
        mask_secret(settings['DAGSHUB_TOKEN'])
        self._private_environment.update(settings)
        return super().execute(context)


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
        last_line = super().execute(context)
        prefix = 'TRAINING_RESULT_JSON='
        if not isinstance(last_line, str) or not last_line.startswith(prefix):
            raise AirflowException(
                'Training did not return a structured model version; deployment blocked'
            )
        result = json.loads(last_line[len(prefix) :])
        if (
            result.get('model_name') != 'movie-genre-knn'
            or not str(result.get('model_version', '')).isdecimal()
            or not result.get('run_id')
        ):
            raise AirflowException('Invalid training result; deployment blocked')
        return result


with DAG(
    dag_id='training_pipeline',
    description='Prepare data, register KNN, then deploy and verify the exact model version.',
    # Previous daily schedule (requires importing CronTriggerTimetable):
    # schedule=CronTriggerTimetable(
    #     '40 9 * * *', timezone='Europe/Berlin', run_immediately=timedelta(0)
    # ),
    # Schedule training when a successful upload emits a rating_parts event.
    schedule=[RATING_PARTS],
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    dagrun_timeout=timedelta(minutes=75),
    tags=['data-preparation', 'knn', 'training', 'movie-reco'],
) as dag:
    prepare_features = BucketPreparationOperator(
        task_id='prepare_features',
        image='movie-reco-data-preparation:local',
        docker_url='unix://var/run/docker.sock',
        api_version='auto',
        force_pull=False,
        # Keep the image entrypoint; no argument means all parts in the bucket.
        mount_tmp_dir=False,
        mounts=[
            Mount('/app/data/processed', str(project / 'data/processed'), type='bind'),
        ],
        # Outbound HTTPS is needed to download the inputs from the DagsHub bucket.
        network_mode='bridge',
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
        do_xcom_push=True,
        # Retrying after partial registration could create another model version.
        retries=0,
        execution_timeout=timedelta(minutes=30),
        labels={'project': 'movie-reco', 'managed_by': 'airflow', 'job': 'train_knn'},
    )

    deploy_predict = PythonOperator(
        task_id='deploy_predict',
        python_callable=deploy_prediction,
        op_kwargs={'training_result': train_knn.output},
        retries=0,
        execution_timeout=timedelta(minutes=20),
    )

    prepare_features >> train_knn >> deploy_predict
