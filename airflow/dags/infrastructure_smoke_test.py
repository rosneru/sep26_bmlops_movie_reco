

"""Manual infrastructure check; no movie data, model training or external writes."""

from datetime import datetime, timedelta, timezone
import logging

from airflow.sdk import DAG, task
from airflow.providers.standard.operators.empty import EmptyOperator


with DAG(
    dag_id='infrastructure_smoke_test',
    description='Verify task execution and logs before connecting the movie pipeline.',
    start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=3),
    default_args={'retries': 0, 'execution_timeout': timedelta(seconds=30)},
    tags=['infrastructure', 'smoke-test'],
) as dag:
    start = EmptyOperator(task_id='start')

    @task
    def log_message():
        logging.getLogger(__name__).info('AIRFLOW_SMOKE_TEST_OK')

    end = EmptyOperator(task_id='end')

    start >> log_message() >> end
