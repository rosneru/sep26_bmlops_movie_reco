import os
import re
from pathlib import Path

import boto3
from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import BotoCoreError, ClientError


class StorageConfigError(Exception):
    """The configuration for the storage is incomplete."""


class StorageError(Exception):
    """The storage could not be reached or rejected a request."""


class BucketStorageClient:
    """Access to the rating data in the DagsHub storage bucket."""

    RATINGS_PREFIX = 'ratings_parts/'
    # Matches e.g. 'ratings_parts/ratings_01.csv', the number is group 1
    RATINGS_KEY_PATTERN = re.compile(r'ratings_parts/ratings_(\d+)\.csv')

    def __init__(self, endpoint_url: str, bucket: str, token: str):
        self.bucket = bucket
        self._client = boto3.client(
            's3',
            endpoint_url=endpoint_url,
            aws_access_key_id=token,
            aws_secret_access_key=token,
            # DagsHub ignores the region, but boto3 may need one
            region_name='us-east-1',
        )

    @classmethod
    def from_env(cls) -> 'BucketStorageClient':
        """Create the storage from the DAGSHUB_* environment variables."""
        names = ('DAGSHUB_S3_ENDPOINT_URL', 'DAGSHUB_BUCKET', 'DAGSHUB_TOKEN')
        values = {name: os.getenv(name) for name in names}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise StorageConfigError(
                f'Missing configuration: set {", ".join(missing)}'
            )
        return cls(*values.values())

    def read_stored_part_numbers(self) -> list[int]:
        """
        Return the sorted numbers of the rating parts already in the bucket.

        Keys under the prefix that are no rating part are ignored.

        Raises
        ------
        StorageError
            If the bucket cannot be listed, e.g. it does not exist.
        """
        # list_objects_v2 returns at most 1000 keys per call, the paginator
        # repeats the call until all keys are read
        paginator = self._client.get_paginator('list_objects_v2')
        pages = paginator.paginate(
            Bucket=self.bucket, Prefix=self.RATINGS_PREFIX
        )
        numbers = []
        try:
            for page in pages:
                # 'Contents' is missing if there are no matching keys
                for obj in page.get('Contents', []):
                    match = self.RATINGS_KEY_PATTERN.fullmatch(obj['Key'])
                    if match:
                        numbers.append(int(match.group(1)))
        except (BotoCoreError, ClientError) as e:
            raise StorageError(
                f'Could not list {self.RATINGS_PREFIX}: {e}'
            ) from e
        return sorted(numbers)

    def exists(self, key: str) -> bool:
        """
        Check whether an object exists in the bucket.

        Only reads the metadata of the object, the file is not downloaded.

        Raises
        ------
        StorageError
            For any error other than "not found", e.g. an invalid token.
        """
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            # S3-compatible services report "not found" with different codes
            if e.response['Error']['Code'] in ('404', 'NoSuchKey', 'NotFound'):
                return False
            raise StorageError(f'Could not check {key}: {e}') from e
        except BotoCoreError as e:
            raise StorageError(f'Could not check {key}: {e}') from e
        return True

    def upload(self, path: Path, key: str) -> None:
        """
        Upload a local file to the bucket under the given key.

        Large files are uploaded in chunks. The object only appears in the
        bucket once the upload is complete, so an interrupted upload leaves
        no partial file behind. An existing object with the same key is
        overwritten, so check with exists() first if that is not intended.

        Raises
        ------
        StorageError
            If the upload fails, e.g. the bucket does not exist.
        """
        try:
            self._client.upload_file(str(path), self.bucket, key)
        except (BotoCoreError, ClientError, S3UploadFailedError) as e:
            raise StorageError(f'Could not upload {path} to {key}: {e}') from e


if __name__ == '__main__':
    client = BucketStorageClient.from_env()
    stored_part_numbers = client.read_stored_part_numbers()
    print(stored_part_numbers)
