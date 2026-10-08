#!/usr/bin/env python3
from safety import SafeError, secret, scrub, api_url, request
import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URLS = {
    "uptime": "https://uptime.betterstack.com/api/v2",
    "uptime-v3": "https://uptime.betterstack.com/api/v3",
    "telemetry": "https://telemetry.betterstack.com/api/v1",
    "errors": "https://errors.betterstack.com/api/v1",
}


RESOURCE_PATHS = {
    ("uptime", "monitors"): "/monitors",
    ("uptime", "status-pages"): "/status-pages",
    ("uptime", "heartbeats"): "/heartbeats",
    ("uptime-v3", "incidents"): "/incidents",
    ("telemetry", "sources"): "/sources",
    ("errors", "applications"): "/applications",
    ("errors", "errors"): "/errors",
}

VALIDATION_ENDPOINTS = [
    ("uptime", "/monitors", "Uptime monitors"),
    ("telemetry", "/sources", "Telemetry sources"),
    ("errors", "/applications", "Errors applications"),
]


class BetterStackError(SafeError):
    pass


def default_team():
    return "explicit-credential"


def token_kind_for_area(area: str) -> str:
    if area.startswith("uptime"):
        return "uptime"
    if area == "errors":
        return "errors"
    return "telemetry"


def token_file_for_team(team, area="uptime"):
    return os.environ.get("BETTERSTACK_TOKEN_FILE", "explicit environment/file only")


def read_token(team=None, area="uptime"):
    kind = token_kind_for_area(area).upper()
    name = "BETTERSTACK_" + kind + "_TOKEN"
    return secret(name, name + "_FILE"), "explicit area credential"


def parse_params(params: list[str]) -> dict:
    parsed = {}
    for item in params:
        if "=" not in item:
            raise BetterStackError(f"--param must be key=value, got: {item}")
        key, value = item.split("=", 1)
        parsed[key] = value
    return parsed


def make_url(area, path, params=None):
    return api_url(BASE_URLS[area], path, params)


def request_json(area, path, *, method="GET", params=None, body=None, timeout=30):
    token, _ = read_token(area=area)
    return request(
        make_url(area, path, params),
        method=method,
        body=body,
        timeout=timeout,
        headers={"Authorization": "Bearer " + token},
    )


def summarize_payload(payload: object) -> object:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        sample = []
        for item in payload["data"][:5]:
            attrs = item.get("attributes", {}) if isinstance(item, dict) else {}
            sample.append(
                {
                    "id": item.get("id") if isinstance(item, dict) else None,
                    "type": item.get("type") if isinstance(item, dict) else None,
                    "name": attrs.get("name")
                    or attrs.get("url")
                    or attrs.get("email")
                    or attrs.get("team_name")
                    or attrs.get("source_group_name"),
                }
            )
        return {"count": len(payload["data"]), "sample": sample}
    if isinstance(payload, dict):
        return payload
    return {"data": payload}


def print_json(payload: object) -> None:
    print(json.dumps(scrub(payload), indent=2, ensure_ascii=False))


def cmd_doctor(_args: argparse.Namespace) -> int:
    team = default_team()
    print(f"betterstack_team={team}")
    exit_code = 0
    for area in ("uptime", "telemetry", "errors"):
        print(f"{area}_token_file={token_file_for_team(team, area)}")
        try:
            _token, source = read_token(team, area)
            print(f"{area}_token=present({source})")
        except (SafeError, OSError, ValueError) as exc:
            print(f"{area}_token=missing_or_invalid({exc})")
            exit_code = 1
    print("uptime_base=https://uptime.betterstack.com/api/v2")
    print("telemetry_base=https://telemetry.betterstack.com/api/v1")
    print("errors_base=https://errors.betterstack.com/api/v1")
    return exit_code


def cmd_validate(args):
    area = args.area
    path = {"uptime": "/monitors", "telemetry": "/sources", "errors": "/applications"}[
        area
    ]
    status, payload = request_json(area, path)
    print_json(
        {
            "area": area,
            "http_status": status,
            "ok": 200 <= status < 300,
            "summary": summarize_payload(payload),
        }
    )
    return 0 if 200 <= status < 300 else 1


def cmd_resource(args: argparse.Namespace) -> int:
    area = args.area
    if args.resource == "incidents" and area == "uptime":
        area = "uptime-v3"
    path = RESOURCE_PATHS[(area, args.resource)]
    status, payload = request_json(area, path, params=parse_params(args.param))
    output = summarize_payload(payload) if args.summary else payload
    print_json({"http_status": status, "ok": 200 <= status < 300, "data": output})
    return 0 if 200 <= status < 300 else 1


def cmd_get(args: argparse.Namespace) -> int:
    status, payload = request_json(
        args.area, args.path, params=parse_params(args.param)
    )
    print_json({"http_status": status, "ok": 200 <= status < 300, "data": payload})
    return 0 if 200 <= status < 300 else 1


def load_json_file(path: str | None) -> object:
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BetterStackError(f"JSON body file is invalid: {path}") from exc


def cmd_mutate(args: argparse.Namespace) -> int:
    body = load_json_file(args.json_file)
    preview = {
        "dry_run": not args.execute,
        "method": args.method.upper(),
        "area": args.area,
        "path": args.path,
        "body_keys": sorted(body.keys()) if isinstance(body, dict) else "non-object",
    }
    if not args.execute:
        print_json(preview)
        return 0

    status, payload = request_json(
        args.area, args.path, method=args.method.upper(), body=body
    )
    print_json({"http_status": status, "ok": 200 <= status < 300, "data": payload})
    return 0 if 200 <= status < 300 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Better Stack API helper for explicit account operations."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Show local config without printing token")
    doctor.set_defaults(func=cmd_doctor)

    validate = sub.add_parser(
        "validate", help="Validate one API area (default: uptime)"
    )
    validate.add_argument(
        "--area", choices=["uptime", "telemetry", "errors"], default="uptime"
    )
    validate.set_defaults(func=cmd_validate)

    for area in ("uptime", "telemetry", "errors"):
        p = sub.add_parser(area, help=f"List common {area} resources")
        if area == "uptime":
            choices = ["monitors", "status-pages", "heartbeats", "incidents"]
        elif area == "telemetry":
            choices = ["sources"]
        else:
            choices = ["applications", "errors"]
        p.add_argument("resource", choices=choices)
        p.add_argument(
            "--param", action="append", default=[], help="Query parameter key=value"
        )
        p.add_argument("--summary", action="store_true")
        p.set_defaults(func=cmd_resource, area=area)

    get = sub.add_parser("get", help="GET an arbitrary API path")
    get.add_argument("area", choices=sorted(BASE_URLS))
    get.add_argument("path")
    get.add_argument(
        "--param", action="append", default=[], help="Query parameter key=value"
    )
    get.set_defaults(func=cmd_get)

    for method in ("post", "patch", "put", "delete"):
        p = sub.add_parser(
            method, help=f"{method.upper()} an arbitrary API path; dry-run by default"
        )
        p.add_argument("area", choices=sorted(BASE_URLS))
        p.add_argument("path")
        p.add_argument("--json-file", help="JSON request body file")
        p.add_argument(
            "--execute", action="store_true", help="Actually send the write request"
        )
        p.set_defaults(func=cmd_mutate, method=method)

    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (SafeError, OSError, ValueError) as exc:
        print(
            "ERROR: "
            + (
                str(exc)
                if isinstance(exc, SafeError)
                else "Invalid input or file; sensitive details suppressed"
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
