#!/usr/bin/env python3
"""Read-only Better Stack SQL HTTP client; never execute supplied shell text."""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import shlex
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_config(config):
    host = config.get('host', '')
    if not re.fullmatch(r'[a-z0-9-]+-connect\.betterstackdata\.com', host):
        raise ValueError('Expected an official Better Stack SQL connection hostname')
    if not config.get('username') or not config.get('password'):
        raise ValueError('Missing SQL username or password')


def execute(config, sql):
    validate_config(config)
    if ';' in sql.rstrip().rstrip(';') or not re.match(r'^\s*(SELECT|WITH|DESCRIBE|SHOW)\b', sql, re.I):
        raise ValueError('Only SELECT, WITH, DESCRIBE or SHOW queries are accepted')
    # Better Stack enforces readonly server-side and rejects attempts to set
    # readonly in the request, even to 1. Prefix validation is an early guard.
    params = urlencode({'max_execution_time': 60,
                        'max_result_rows': 1000, 'result_overflow_mode': 'throw'})
    auth = base64.b64encode((config['username'] + ':' + config['password']).encode()).decode()
    request = Request('https://' + config['host'] + '/?' + params,
                      data=sql.encode(), method='POST',
                      headers={'Authorization': 'Basic ' + auth,
                               'Content-Type': 'text/plain; charset=utf-8'})
    try:
        with build_opener(NoRedirect()).open(request, timeout=70) as response:
            return response.read().decode()
    except HTTPError as error:
        # Error bodies can echo queries, credential-bearing URLs or data.
        raise ValueError('SQL HTTP %s; response body suppressed' % error.code) from None


def read_config(path):
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError('Credential file must be a regular private file (chmod 600)')
    config = json.loads(path.read_text())
    validate_config(config)
    return config


def install(source, destination):
    if source.is_symlink():
        raise ValueError('Refusing symlink credential sample')
    source.chmod(0o600)
    args = shlex.split(source.read_text().replace('\\\n', ''))
    if not args or Path(args[0]).name != 'curl':
        raise ValueError('Expected a curl sample, parsed as data, never executed')
    credential = None
    url = None
    sample_sql = None
    for index, arg in enumerate(args):
        if arg in ('-u', '--user'):
            credential = args[index + 1]
        elif arg.startswith('https://'):
            url = arg
        elif arg in ('-d', '--data', '--data-raw', '--data-binary'):
            sample_sql = args[index + 1]
    if not credential or ':' not in credential or not url:
        raise ValueError('Sample must contain explicit -u username:password and HTTPS URL')
    parsed = urlsplit(url)
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('Unexpected endpoint userinfo or port')
    username, password = credential.split(':', 1)
    config = {'host': parsed.hostname, 'username': username, 'password': password}
    validate_config(config)
    if execute(config, 'SELECT 1 AS connection_ok FORMAT JSONEachRow').strip() != '{"connection_ok":1}':
        raise ValueError('Unexpected SQL connection test result')
    # The supplied sample only enumerates static collection names. Do not execute
    # arbitrary sample SQL or copy it into durable credential storage.
    config['collections'] = sorted(set(re.findall(r'\bt\d+_[a-z0-9_]+(?=[\x27\x22])', sample_sql or '')))
    if destination.parent.is_symlink():
        raise ValueError('Refusing symlink configuration directory')
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination.parent.chmod(0o700)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(config, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'connection_ok': True, 'credential_file': str(destination),
                      'mode': '0600', 'host': config['host'], 'collections': config['collections']}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(os.environ.get(
        'BETTERSTACK_SQL_CONFIG_FILE', '~/.config/betterstack-ops/sql.json')).expanduser())
    subs = parser.add_subparsers(dest='command', required=True)
    setup = subs.add_parser('install-curl')
    setup.add_argument('--file', required=True, type=Path)
    subs.add_parser('check')
    query = subs.add_parser('query')
    query.add_argument('--file', required=True, type=Path)
    args = parser.parse_args()
    if args.command == 'install-curl':
        install(args.file, args.config)
    else:
        config = read_config(args.config)
        sql = ('SELECT 1 AS connection_ok FORMAT JSONEachRow' if args.command == 'check'
               else args.file.read_text())
        print(execute(config, sql), end='')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Only controlled ValueError text is safe to emit; never echo credentials.
        print('SQL operation failed; check input, credential permissions and endpoint. Sensitive details suppressed.', file=sys.stderr)
        sys.exit(1)
