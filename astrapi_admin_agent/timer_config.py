# astrapi_admin_agent/timer_config.py
"""Server-seitig einstellbares Poll-Intervall (E-011).

astrapi-admin-agent ist rein pull-basiert -- der Server kann dem Agenten
nichts "pushen". Stattdessen liefert er das gewuenschte Intervall bei
jedem ohnehin stattfindenden Poll (GET /api/agent/policy) mit; dieses
Modul gleicht bei Abweichung den EIGENEN systemd-Timer per
Drop-in-Override ab. Wirkt deshalb erst beim naechsten Poll-Zyklus,
nicht sofort -- der zuletzt konfigurierte Intervall gilt bis dahin
weiter.
"""
import subprocess
import sys
from pathlib import Path

DROPIN_DIR = Path("/etc/systemd/system/astrapi-admin-agent.timer.d")
DROPIN_PATH = DROPIN_DIR / "override.conf"


def _dropin_content(minutes: int) -> str:
    # Die erste, leere OnUnitActiveSec=-Zeile setzt den von der Basis-.timer
    # geerbten 15min-Wert zurueck -- Drop-ins sind fuer wiederholbare
    # Direktiven wie OnUnitActiveSec additiv, ohne den Reset wuerden beide
    # Intervalle gleichzeitig gelten (der Timer liefe dann am kuerzeren).
    return (
        "# Verwaltet von astrapi-admin-agent -- Wert kommt vom Server\n"
        "# (astrapi-admin: Einstellungen > Agent). Nicht von Hand bearbeiten,\n"
        "# wird beim naechsten Poll ueberschrieben.\n"
        "[Timer]\n"
        "OnUnitActiveSec=\n"
        f"OnUnitActiveSec={minutes}min\n"
    )


def apply_poll_interval(minutes: int) -> None:
    """Best-effort -- darf cmd_apply() nie zum Absturz bringen (analog zur
    Proxmox-LXC-Erkennung beim Pairing, die denselben "nie den Hauptablauf
    gefaehrden"-Grundsatz verfolgt). No-op (kein Schreiben, kein
    daemon-reload/restart), wenn der Drop-in bereits den gewuenschten
    Wert enthaelt -- vermeidet einen Timer-Neustart bei jedem einzelnen
    Poll-Zyklus."""
    try:
        content = _dropin_content(minutes)
        if DROPIN_PATH.exists() and DROPIN_PATH.read_text() == content:
            return

        from astrapi_admin_agent.config import atomic_write

        DROPIN_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write(DROPIN_PATH, content, mode=0o644)
        subprocess.run(["systemctl", "daemon-reload"], timeout=10)
        # Timer (nicht Service) neu starten, damit der naechste Lauf ab JETZT
        # im neuen Intervall neu berechnet wird -- ein reines daemon-reload
        # wuerde den naechsten Lauf noch nach dem alten Zeitplan ausloesen.
        subprocess.run(["systemctl", "restart", "astrapi-admin-agent.timer"], timeout=10)
    except Exception as e:
        print(f"Warnung: Poll-Intervall konnte nicht angepasst werden: {e}", file=sys.stderr)
