# astrapi_admin_agent/services.py
"""systemd-Service-Zustand durchsetzen -- nur die Differenz zum Ziel
nachziehen (is-enabled/is-active pruefen, dann gezielt enable/start/
disable/stop), kein blindes Neu-Anwenden bei jedem Lauf."""
import subprocess

# Welche (enabled, active) das jeweilige Zielwort bedeutet. None = diese
# Achse wird von diesem Zielzustand nicht angefasst (z.B. "started" laesst
# den Enabled-Status unangetastet).
_STATE_TARGETS = {
    "enabled_started": {"enabled": True, "active": True},
    "enabled": {"enabled": True, "active": None},
    "started": {"enabled": None, "active": True},
    "disabled_stopped": {"enabled": False, "active": False},
    "disabled": {"enabled": False, "active": None},
    "stopped": {"enabled": None, "active": False},
}

# apply.py sortiert Services danach, ob ihr Zielzustand "Praesenz" oder
# "Abwesenheit" durchsetzt -- Abwesenheit laeuft erst in der letzten,
# separat getesteten Phase (siehe apply.py).
PRESENCE_STATES = {"enabled_started", "enabled", "started"}
ABSENCE_STATES = {"disabled_stopped", "disabled", "stopped"}


def is_enabled(name: str) -> bool:
    r = subprocess.run(["systemctl", "is-enabled", name], capture_output=True, text=True)
    return r.stdout.strip() == "enabled"


def is_active(name: str) -> bool:
    r = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True)
    return r.stdout.strip() == "active"


def apply_state(name: str, target_state: str) -> tuple[bool, str]:
    """Gibt (ok, detail) zurueck. detail beschreibt entweder die
    ausgefuehrten Aktionen oder "bereits im Zielzustand"."""
    target = _STATE_TARGETS.get(target_state)
    if target is None:
        return False, f"Unbekannter Zielzustand: {target_state}"

    actions = []
    if target["enabled"] is True and not is_enabled(name):
        actions.append("enable")
    elif target["enabled"] is False and is_enabled(name):
        actions.append("disable")
    if target["active"] is True and not is_active(name):
        actions.append("start")
    elif target["active"] is False and is_active(name):
        actions.append("stop")

    if not actions:
        return True, "bereits im Zielzustand"

    log = []
    for action in actions:
        r = subprocess.run(["systemctl", action, name], capture_output=True, text=True)
        log.append(f"{action}: {(r.stdout + r.stderr).strip()}")
        if r.returncode != 0:
            return False, "\n".join(log)
    return True, "\n".join(log)
