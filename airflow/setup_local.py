"""Generate missing local Airflow keys and a persistent dashboard password.

Run with Python from any directory. Uses only the standard library, preserves
existing nonempty settings, and never prints secrets. PostgreSQL setup is kept
separate; this script does not initialize the database or start containers.
"""

import base64
import os
import re
import secrets
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    env_path = root / '.env'
    content = env_path.read_text(encoding='utf-8-sig') if env_path.exists() else ''
    # DockerOperator talks directly to the Linux daemon, so Windows drive paths
    # need Docker Desktop's host mount prefix. Users can override this in .env.
    docker_project_dir = root.as_posix()
    if os.name == 'nt':
        drive = root.drive.rstrip(':').lower()
        relative = '/'.join(root.parts[1:])
        docker_project_dir = f'/run/desktop/mnt/host/{drive}/{relative}'
    candidates = {
        'AIRFLOW_FERNET_KEY': base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode(),
        'AIRFLOW_JWT_SECRET': secrets.token_hex(32),
        'AIRFLOW_ADMIN_USER': 'airflow',
        'AIRFLOW_ADMIN_PASSWORD': secrets.token_urlsafe(24),
        'AIRFLOW_DOCKER_PROJECT_DIR': docker_project_dir,
        'AIRFLOW_DOCKER_GID': '0',
    }
    for key, value in candidates.items():
        pattern = re.compile(rf'^{key}=(.*)$', re.MULTILINE)
        match = pattern.search(content)
        if match:
            if match.group(1).strip() not in {'', '""', "''"}:
                continue
            content = pattern.sub(lambda _, line=f'{key}={value}': line, content)
        else:
            content = content.rstrip() + f'\n{key}={value}\n'
    env_path.write_text(content, encoding='utf-8')

    (root / 'airflow' / 'dags').mkdir(parents=True, exist_ok=True)
    print('Local Airflow keys and dashboard credentials are ready.')
    print('Dashboard username/password location: root .env (ignored by Git)')


if __name__ == '__main__':
    main()
