# astrapi_admin_agent/state.py
"""Lokaler Zustands-Cache unter /var/lib/astrapi-admin/state.json:
managed_paths (Grundlage fuer die Loeschsicherheitsregel in
files.remove_if_managed -- nur was astrapi-admin selbst angelegt hat,
darf bei action=absent wieder verschwinden) und policy_hash fuers
spaetere No-Op-Kurzschluss (Policy unveraendert + letzter Lauf ohne
Fehler -> nur ein leichter "unveraendert"-Report)."""
import json
import os
from pathlib import Path

DEFAULTS = {"policy_hash": "", "managed_paths": []}

_STATE_DIR = Path("/var/lib/astrapi-admin")


def state_path() -> Path:
    return _STATE_DIR / "state.json"


def load() -> dict:
    p = state_path()
    if not p.exists():
        return dict(DEFAULTS)
    data = json.loads(p.read_text())
    return {**DEFAULTS, **data}


def save(state: dict) -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = state_path().with_name(f".state.json.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    os.replace(tmp, state_path())
