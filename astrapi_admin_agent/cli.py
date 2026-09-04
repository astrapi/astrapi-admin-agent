# astrapi_admin_agent/cli.py
import argparse
import os
import socket
import sys

import httpx

from astrapi_admin_agent import apply as applymod
from astrapi_admin_agent import config as cfgmod
from astrapi_admin_agent import pkg, timer_config
from astrapi_admin_agent import users as usersmod
from astrapi_admin_agent.api_client import ApiClient
from astrapi_admin_agent.osinfo import detect_os_type


def _require_root(action: str) -> bool:
    """Prueft frueh statt erst beim ersten fehlschlagenden Syscall --
    bei 'pair' insbesondere, damit der einmalige Pairing-Code nicht schon
    beim Server eingeloest wird, bevor klar ist, dass die Konfiguration
    danach gar nicht gespeichert werden kann."""
    if os.geteuid() == 0:
        return True
    print(f"Muss als root laufen (z.B. mit sudo) -- {action}.", file=sys.stderr)
    return False


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
    if not _require_root("die Konfiguration wird sonst nach dem Pairing nicht gespeichert"):
        return 1

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

    try:
        timer_config.enable_now()
        print("Periodischer Timer aktiviert (astrapi-admin-agent.timer).")
    except Exception as e:
        print(
            f"Warnung: Timer konnte nicht aktiviert werden ({e}) -- bitte manuell "
            "'systemctl enable --now astrapi-admin-agent.timer' ausführen, sonst "
            "läuft der Agent nur bis zum nächsten Neustart.",
            file=sys.stderr,
        )
    return 0


def cmd_apply(args) -> int:
    if not _require_root("Pakete/Services/Config-Dateien lassen sich sonst nicht anwenden"):
        return 1

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

    # E-011: server-seitig einstellbares Poll-Intervall -- unabhaengig von
    # der eigentlichen Policy-Konvergenz, deshalb hier vorgezogen.
    timer_config.apply_poll_interval(policy.get("poll_interval_minutes") or 15)

    backend = pkg.detect_backend()

    # Reiner Status-Check laeuft IMMER, unabhaengig von pending_action --
    # billig, rein lesend, liefert die Update-Anzeige unabhaengig davon,
    # ob je ein Update angestossen wird. Security-Teilmenge nur fuer apt
    # (Debian) sinnvoll (E-008) -- Arch/pacman hat dafuer keine
    # vergleichbare Kategorisierung, siehe list_security_upgradable().
    upgradable = pkg.list_upgradable(backend)
    security_upgradable = pkg.list_security_upgradable(backend) if backend == "apt" else []

    # Echtes Update NUR, wenn der Server das ueber pending_action explizit
    # angefordert hat (E-007) -- laeuft vor der normalen Policy-Konvergenz,
    # damit frisch installierte/aktualisierte Pakete in derselben Runde
    # schon beruecksichtigt werden.
    update_result = None
    if policy.get("pending_action") == "update":
        # Schnappschuss VOR dem eigentlichen Upgrade -- das sind die
        # Pakete, die tatsaechlich aktualisiert werden sollen; nach dem
        # Upgrade ist 'upgradable' idealerweise (fast) leer und wuerde
        # nicht mehr zeigen, was gerade passiert ist.
        applied_packages = list(upgradable)
        if backend:
            ok, output = pkg.upgrade_all(backend)
            update_result = {"ok": ok, "detail": output, "packages": applied_packages}
        else:
            update_result = {
                "ok": False,
                "detail": "kein unterstützter Paket-Manager gefunden",
                "packages": [],
            }
        upgradable = pkg.list_upgradable(backend)
        security_upgradable = pkg.list_security_upgradable(backend) if backend == "apt" else []

    result = applymod.apply_policy(policy)
    status, summary = applymod.summarize(policy, result)

    result["updates_available"] = len(upgradable)
    result["upgradable_packages"] = upgradable
    # reboot_required()/inventory() sind reine Anreicherung des Reports --
    # anders als die eigentliche Policy-Konvergenz duerfen sie den ganzen
    # apply()-Zyklus nie zum Absturz bringen (sonst kaeme ueberhaupt kein
    # Report beim Server an, schlimmer als ein normaler Fehlerstatus).
    try:
        result["reboot_required"] = pkg.reboot_required(backend)
    except Exception as e:
        print(f"Warnung: Neustart-Status konnte nicht ermittelt werden: {e}", file=sys.stderr)
        result["reboot_required"] = False
    # E-012: rein informative Bestandsaufnahme -- laeuft IMMER, unabhaengig
    # davon, ob je eine Nutzer-Policy zugewiesen wurde.
    try:
        result["user_inventory"] = usersmod.inventory()
    except Exception as e:
        print(f"Warnung: Nutzer-Bestandsaufnahme fehlgeschlagen: {e}", file=sys.stderr)
        result["user_inventory"] = []
    if backend == "apt":
        result["security_updates_available"] = len(security_upgradable)
        result["security_upgradable_packages"] = security_upgradable
    if update_result is not None:
        result["update_result"] = update_result
        if not update_result["ok"]:
            status = "error"
            summary = f"Update fehlgeschlagen -- {summary}" if summary != "keine Änderungen nötig" else "Update fehlgeschlagen"

    print(f"Status: {status} -- {summary}")
    if update_result is not None:
        print(f"  Update: {update_result}")
    print(f"  Verfügbare Updates: {len(upgradable)}")
    if backend == "apt":
        print(f"  davon sicherheitsrelevant: {len(security_upgradable)}")
    for item in result["packages"] + result["services"] + result["config_files"] + result["users"]:
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
