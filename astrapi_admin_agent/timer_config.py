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
from datetime import datetime, timedelta
from pathlib import Path

DROPIN_DIR = Path("/etc/systemd/system/astrapi-admin-agent.timer.d")
DROPIN_PATH = DROPIN_DIR / "override.conf"


def _dropin_content(minutes: int) -> str:
    # T-320-ADMIN: FRUEHER stand hier zusaetzlich eine leere
    # "OnUnitActiveSec=\n"-Zeile vor dieser Zuweisung, um den von der
    # Basis-.timer geerbten 15min-Wert zurueckzusetzen (Drop-ins sind fuer
    # wiederholbare Direktiven wie OnUnitActiveSec additiv). Live auf
    # `backup-dev` reproduziert: genau dieser Reset-dann-Neuzuweisen-Trick
    # bringt systemd 257 (Debian trixie) dazu, fuer den Timer nie wieder
    # einen "next" Termin zu berechnen ("active (elapsed)"/"Trigger: n/a",
    # dauerhaft, kein automatischer Lauf mehr). Ohne Drop-in oder mit einer
    # einfachen Zuweisung ohne Reset funktioniert derselbe Timer sofort
    # wieder normal. Deshalb jetzt: kein Reset mehr noetig, weil
    # OnUnitActiveSec inzwischen NICHT MEHR in der Basis-.timer steht
    # (nur dort per Drop-in gesetzt) -- Bootstrap vor dem ersten Poll laeuft
    # stattdessen ueber OnBootSec/OnActiveSec in der Basis-.timer.
    return (
        "# Verwaltet von astrapi-admin-agent -- Wert kommt vom Server\n"
        "# (astrapi-admin: Einstellungen > Agent). Nicht von Hand bearbeiten,\n"
        "# wird beim naechsten Poll ueberschrieben.\n"
        "[Timer]\n"
        f"OnUnitActiveSec={minutes}min\n"
    )


def enable_now() -> None:
    """Aktiviert den Timer dauerhaft (ueberlebt einen Reboot) -- ohne das
    bliebe ein frisch gepaarter Host nur bis zum naechsten Neustart aktiv:
    weder das Debian-/Arch-Paket (kein Postinst-Mechanismus im
    astrapi-packages-Build, nur ein blosses `install` der Unit-Dateien)
    noch dieser Agent an anderer Stelle rufen 'systemctl enable' auf.
    Ohne diesen Schritt haette ein Host nach einem Reboot (z.B. nach einem
    selbst ausgeloesten Kernel-Update) den periodischen Poll-Zyklus
    dauerhaft verloren, bis jemand von Hand nachhilft (T-303-ADMIN)."""
    subprocess.run(
        ["systemctl", "enable", "--now", "astrapi-admin-agent.timer"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )


def next_run_at(poll_interval_minutes: int) -> str:
    """Schaetzt den naechsten geplanten Timer-Lauf als jetzt + Poll-Intervall.

    Fruehere Umsetzung (T-309-ADMIN) fragte den Wert live per
    `systemctl list-timers --output=json` bei systemd ab -- das scheitert
    strukturell, wenn der Aufruf (wie hier) aus `cmd_apply()` selbst heraus
    passiert: `astrapi-admin-agent.service` ist zu diesem Zeitpunkt noch
    "active (running)", und `OnUnitActiveSec` kennt seinen naechsten Termin
    erst, sobald DIESE Aktivierung abgeschlossen ist -- bis dahin liefert
    systemd kein "next". Live an einem echten Host reproduziert
    (T-318-ADMIN): jeder einzelne automatische Report enthielt
    "next_run_at": null, obwohl derselbe `systemctl`-Aufruf ausserhalb von
    `cmd_apply()` (manuell oder aus einem fremden Service heraus) immer
    einen validen Wert lieferte. Eine simple Schaetzung ab dem aktuellen
    Zeitpunkt braucht kein systemd/D-Bus mehr und ist fuer die Anzeige
    "Naechster Lauf" ausreichend genau -- RandomizedDelaySec-Jitter und die
    verbleibende Restlaufzeit von cmd_apply() nach diesem Aufruf liegen im
    Bereich weniger Sekunden, irrelevant fuer eine minutengenaue Anzeige."""
    return (datetime.now() + timedelta(minutes=poll_interval_minutes)).strftime("%Y-%m-%d %H:%M:%S")


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
