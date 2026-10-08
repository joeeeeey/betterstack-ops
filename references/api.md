# Official API and runtime notes

Reviewed 2026-10-08. Public documentation is authoritative for the target account/version.

## [Uptime API](https://betterstack.com/docs/uptime/api/getting-started-with-uptime-api/)

Bearer API authentication; monitor API v2 and incidents v3.

## [SQL remote access](https://betterstack.com/docs/logs/query-api/connect-remotely/)

SQL uses dedicated connection credentials and official *-connect.betterstackdata.com endpoints.

## Boundaries

Python 3.10+. Set `BETTERSTACK_UPTIME_TOKEN`, `BETTERSTACK_TELEMETRY_TOKEN` and/or `BETTERSTACK_ERRORS_TOKEN` (each supports `_FILE`). No fallback between API areas. SQL uses `--config /private/path/sql.json` with host, username and password from Better Stack's Connect remotely page; REST tokens are not SQL passwords.

Single-page REST responses; use --param page=... where supported. SQL results can contain sensitive logs and must not be published blindly. SQL connections are separate from REST tokens. No automatic monitor creation from vague alert requirements; generic writes need an exact provider payload.

HTTP helpers do not follow redirects or automatically retry writes. A timeout can mean an unknown outcome; inspect the target before retrying. Secret-field redaction is defense in depth, not a guarantee that arbitrary free text is safe to publish.
