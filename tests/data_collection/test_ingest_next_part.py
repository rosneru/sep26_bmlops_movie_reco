"""Tests for the next_part mode of the data collection service, with a fake bucket."""

import pytest
from pydantic import ValidationError

from data_collection_service import ingest
from data_collection_service.ingest import IngestRequest, ingest_up_to


class FakeBucket:
    def __init__(self, keys):
        self.keys = set(keys)

    def read_stored_part_numbers(self):
        return sorted(
            int(match.group(1))
            for key in self.keys
            if (
                match
                := ingest.BucketStorageClient.RATINGS_KEY_PATTERN.fullmatch(key)
            )
        )

    def exists(self, key):
        return key in self.keys

    def upload(self, path, key):
        self.keys.add(key)


@pytest.fixture
def local_parts(tmp_path, monkeypatch):
    """Four local rating parts and movies.csv."""
    parts_dir = tmp_path / 'ratings_parts'
    parts_dir.mkdir()
    for number in range(1, 5):
        (parts_dir / f'ratings_{number:02d}.csv').write_text('userId\n1\n')
    movies = tmp_path / 'movies.csv'
    movies.write_text('movieId\n1\n')
    monkeypatch.setattr(ingest, 'RATINGS_PARTS_DIR', parts_dir)
    monkeypatch.setattr(ingest, 'MOVIES_PATH', movies)


def use_bucket(monkeypatch, keys):
    bucket = FakeBucket(keys)
    monkeypatch.setattr(ingest.BucketStorageClient, 'from_env', lambda: bucket)
    return bucket


def part_key(number):
    return f'ratings_parts/ratings_{number:02d}.csv'


def test_next_part_uploads_only_the_following_part(local_parts, monkeypatch):
    use_bucket(monkeypatch, ['movies.csv', part_key(1), part_key(2)])

    response = ingest_up_to(None, next_part=True)

    assert response.status == 'ingested'
    assert response.requested_up_to == 3
    assert response.uploaded == [part_key(3)]
    assert response.skipped == ['movies.csv', part_key(1), part_key(2)]


def test_next_part_starts_with_part_one_in_an_empty_bucket(
    local_parts, monkeypatch
):
    use_bucket(monkeypatch, [])

    response = ingest_up_to(None, next_part=True)

    assert response.status == 'ingested'
    assert response.uploaded == ['movies.csv', part_key(1)]


def test_next_part_reports_up_to_date_when_all_parts_are_stored(
    local_parts, monkeypatch
):
    bucket = use_bucket(
        monkeypatch, ['movies.csv'] + [part_key(n) for n in range(1, 5)]
    )

    response = ingest_up_to(None, next_part=True)

    assert response.status == 'up_to_date'
    assert response.requested_up_to == 4
    assert response.uploaded == []
    assert len(bucket.keys) == 5


def test_next_part_cannot_be_combined_with_requested_up_to():
    with pytest.raises(
        ValidationError, match='either requested_up_to or next_part'
    ):
        IngestRequest(requested_up_to=2, next_part=True)


def test_requested_up_to_still_uploads_the_range(local_parts, monkeypatch):
    use_bucket(monkeypatch, ['movies.csv', part_key(1)])

    response = ingest_up_to(3)

    assert response.uploaded == [part_key(2), part_key(3)]
