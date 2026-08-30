# astrapi_admin_agent/config.py
"""Lokale Konfiguration des Agenten: Server-URL + Host-Token.

Der Agent laeuft immer als root (braucht Rechte fuer Pakete/Services/
beliebige Config-Pfade) -- anders als astrapi-sync-cli (User-Space,
XDG_CONFIG_HOME) liegt die Config deshalb root-only unter /etc, nicht
im Home-Verzeichnis eines Users. Kein Multi-User-Fall wie bei sync,
daher genuegt Dateimodus 0600 ohne OS-Keyring.
"""
import json
import os
from pathlib import Path

DEFAULTS = {"server_url": "", "host_token": "", "host_id": "", "hostname": ""}

_CONFIG_DIR = Path("/etc/astrapi-admin")


def config_path() -> Path:
    return _CONFIG_DIR / "config.json"


def load() -> dict:
    p = config_path()
    if not p.exists():
        return dict(DEFAULTS)
    data = json.loads(p.read_text())
    return {**DEFAULTS, **data}


def atomic_write(path: Path, content: str, mode: int | None = None) -> None:
    """Schreibt content atomar (Temp-Datei im selben Verzeichnis + os.replace()).

    Bricht der Prozess mitten im Schreiben ab, bleibt dank atomarem Rename
    immer entweder die alte oder die neue vollstaendige Datei stehen, nie
    ein kaputter Zwischenzustand. Mit gesetztem `mode` bekommt die
    Temp-Datei ihre Rechte im selben Syscall wie das Anlegen, dann ersetzt
    os.replace() atomar die Zieldatei -- kein Zeitfenster mit zu weiten
    Rechten (identisches Idiom wie astrapi_sync_cli.config.atomic_write)."""
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    data = content.encode()
    if mode is not None:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    else:
        tmp.write_bytes(data)
    os.replace(tmp, path)


def save(cfg: dict) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write(config_path(), json.dumps(cfg, indent=2, ensure_ascii=False), mode=0o600)
