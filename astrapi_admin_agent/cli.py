# astrapi_admin_agent/cli.py
import argparse
import socket
import sys

import httpx

from astrapi_admin_agent import apply as applymod
from astrapi_admin_agent import config as cfgmod
from astrapi_admin_agent.api_client import ApiClient
from astrapi_admin_agent.osinfo import detect_os_type


def _server_detail(response: httpx.Response) -> str:
    """Extrahiert FastAPIs "detail"-Feld aus einer Fehlerantwort, falls
    vorhanden, statt des rohen Response-Texts (wie astrapi_sync_cli.cli)."""
    try:
        body = response.json()
    except ValueError:
        return response.text or f"{response.status_code} {response.reason_phrase}"
    if isinstance(body, dict) and "detail" in body:
        return str(body["detail"])
    return response.text or f"{response.status_code} {response.reason_phrase}"


def _format_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return _server_detail(exc.response)
    if isinstance(exc, httpx.RequestError):
        return f"Server nicht erreichbar ({exc})"
    return str(exc)


def cmd_pair(args) -> int:
    hostname = args.hostname or socket.gethostname()
    os_type = args.os_type or detect_os_type()

    try:
        result = ApiClient.pair(args.server_url, args.pairing_code, hostname, os_type)
    except Exception as exc:
        print(f"Pairing fehlgeschlagen: {_format_error(exc)}", file=sys.stderr)
        return 1

    cfg = cfgmod.load()
    cfg["server_url"] = args.server_url.rstrip("/")
    cfg["host_token"] = result["host_token"]
    cfg["host_id"] = result["host_id"]
    cfg["hostname"] = hostname

    try:
        cfgmod.save(cfg)
    except PermissionError:
        print(
            f"Keine Schreibrechte für {cfgmod.config_path()} -- als root ausführen "
            "(z.B. mit sudo).",
            file=sys.stderr,
        )
        return 1

    print(f"Gekoppelt als Host {result['host_id']} ({hostname}, {os_type or 'OS unbekannt'}).")
    print(f"Konfiguration gespeichert unter {cfgmod.config_path()}")
    return 0


def cmd_apply(args) -> int:
    cfg = cfgmod.load()
    if not cfg.get("host_token"):
        print("Noch nicht gekoppelt -- siehe 'astrapi-admin-agent pair'.", file=sys.stderr)
        return 1

    client = ApiClient(cfg["server_url"], cfg["host_token"])

    try:
        policy = client.get_policy()
    except Exception as exc:
        print(f"Policy-Abruf fehlgeschlagen: {_format_error(exc)}", file=sys.stderr)
        return 1

    result = applymod.apply_policy(policy)
    status, summary = applymod.summarize(policy, result)

    print(f"Status: {status} -- {summary}")
    for item in result["packages"] + result["services"] + result["config_files"]:
        if item["status"] != "ok":
            print(f"  {item}")
    for conflict in policy.get("conflicts", []):
        print(f"  Policy-Konflikt (Server): {conflict}")

    try:
        client.report(status, summary, result)
    except Exception as exc:
        print(f"Report konnte nicht gesendet werden: {_format_error(exc)}", file=sys.stderr)
        return 1

    return 1 if status == "error" else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="astrapi-admin-agent")
    sub = p.add_subparsers(dest="command", required=True)

    pp = sub.add_parser("pair", help="Host mit einem astrapi-admin-Server koppeln")
    pp.add_argument("server_url", help="z.B. http://admin.simpsons.lan:5005")
    pp.add_argument("pairing_code", help="Im Server-UI unter Hosts -> 'Host koppeln' erzeugt")
    pp.add_argument("--hostname", default="", help="Anzeigename (Default: echter Hostname)")
    pp.add_argument(
        "--os-type",
        default="",
        choices=["", "archlinux", "debian"],
        help="Override der Auto-Erkennung aus /etc/os-release",
    )
    pp.set_defaults(func=cmd_pair)

    ap = sub.add_parser("apply", help="Aktuelle Policy vom Server abrufen und anwenden")
    ap.set_defaults(func=cmd_apply)

    return p


def main() -> None:
    args = build_parser().parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
