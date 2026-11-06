"""Send a small batch of requests to the local movie prediction API."""

import argparse
import json
from collections import Counter
from getpass import getpass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = 'http://localhost:8000'


def post(path, body, headers):
    request = Request(BASE_URL + path, data=body, headers=headers)
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, b''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id', type=int, default=4)
    parser.add_argument('--username', default='alice')
    parser.add_argument('--authenticated', type=int, default=30)
    parser.add_argument('--unauthenticated', type=int, default=10)
    args = parser.parse_args()
    if args.authenticated < 0 or args.unauthenticated < 0:
        parser.error('Request counts must be zero or greater.')

    headers = {'Content-Type': 'application/json'}
    authenticated_headers = headers.copy()
    if args.authenticated:
        password = getpass(f'API password for {args.username}: ')
        login = urlencode({'username': args.username, 'password': password})
        status, response = post(
            '/token',
            login.encode(),
            {'Content-Type': 'application/x-www-form-urlencoded'},
        )
        if status != 200:
            raise SystemExit(f'Login failed with HTTP {status}.')
        token = json.loads(response)['access_token']
        authenticated_headers['Authorization'] = f'Bearer {token}'

    # Both batches send the same prediction. Only the authorization header changes.
    prediction = json.dumps({'user_ids': [args.user_id], 'seed': 42}).encode()
    batches = [
        ('With a token', args.authenticated, authenticated_headers),
        ('Without a token', args.unauthenticated, headers),
    ]
    for label, count, request_headers in batches:
        statuses = Counter()
        for _ in range(count):
            status, _ = post('/predict', prediction, request_headers)
            statuses[status] += 1
        for status, total in sorted(statuses.items()):
            print(f'{label:16} {total:3} x HTTP {status}')


if __name__ == '__main__':
    try:
        main()
    except (URLError, TimeoutError) as error:
        raise SystemExit(f'Could not reach the local prediction API: {error}') from error
