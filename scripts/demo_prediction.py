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
    parser.add_argument('--failed-logins', type=int, default=10)
    parser.add_argument('--invalid-tokens', type=int, default=10)
    args = parser.parse_args()
    if any(count < 0 for count in (
        args.authenticated, args.unauthenticated,
        args.failed_logins, args.invalid_tokens,
    )):
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

    # Missing tokens count as HTTP 401, but do not emit an auth_events_total event.
    prediction = json.dumps({'user_ids': [args.user_id], 'seed': 42}).encode()
    bad_login = urlencode({
        'username': 'nonexistent-demo-user',
        'password': 'deliberately-wrong-password',
    }).encode()
    invalid_headers = {
        **headers,
        'Authorization': 'Bearer deliberately-invalid-token',
    }
    batches = [
        ('With a token', args.authenticated, '/predict', prediction, authenticated_headers),
        ('Without a token', args.unauthenticated, '/predict', prediction, headers),
        ('Failed login', args.failed_logins, '/token', bad_login,
         {'Content-Type': 'application/x-www-form-urlencoded'}),
        ('Invalid token', args.invalid_tokens, '/predict', prediction, invalid_headers),
    ]
    for label, count, path, body, request_headers in batches:
        statuses = Counter()
        for _ in range(count):
            status, _ = post(path, body, request_headers)
            statuses[status] += 1
        for status, total in sorted(statuses.items()):
            print(f'{label:16} {total:3} x HTTP {status}')

    print('Grafana: allow at least 15 seconds for a scrape and refresh the dashboard.')
    print('For newly created auth event lines, repeat after 30 seconds to show increases.')


if __name__ == '__main__':
    try:
        main()
    except (URLError, TimeoutError) as error:
        raise SystemExit(f'Could not reach the local prediction API: {error}') from error
