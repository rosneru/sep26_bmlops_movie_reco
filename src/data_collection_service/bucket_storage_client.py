import os
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


class StorageConfigError(Exception):
    """The configuration for the storage is incomplete."""


class BucketStorageClient:
    """Access to the rating data in the DagsHub storage bucket."""

    RATINGS_PREFIX = 'ratings_parts/'

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
        """Return the numbers of the rating parts already in the bucket."""
        response = self._client.list_objects_v2(
            Bucket=self.bucket, Prefix=self.RATINGS_PREFIX
        )
        return response.get('Contents', [])

    def exists(self, key: str) -> bool:
        """
        Check whether an object exists in the bucket.

        Only reads the metadata of the object, the file is not downloaded.

        Raises
        ------
        botocore.exceptions.ClientError
            For any error other than "not found", e.g. an invalid token.
        """
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            # S3-compatible services report "not found" with different codes
            if e.response['Error']['Code'] in ('404', 'NoSuchKey', 'NotFound'):
                return False
            raise
        return True

    def upload(self, path: Path, key: str) -> None:
        """
        Upload a local file to the bucket under the given key.

        Large files are uploaded in chunks. The object only appears in the
        bucket once the upload is complete, so an interrupted upload leaves
        no partial file behind. An existing object with the same key is
        overwritten, so check with exists() first if that is not intended.
        """
        self._client.upload_file(str(path), self.bucket, key)


if __name__ == '__main__':
    client = BucketStorageClient.from_env()
    stored_part_numbers = client.read_stored_part_numbers()
    print(stored_part_numbers)
