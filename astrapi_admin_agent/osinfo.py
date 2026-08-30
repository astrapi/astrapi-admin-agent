# astrapi_admin_agent/osinfo.py
"""Erkennt die Distro anhand von /etc/os-release -- fuer das Server-Feld
os_type (bestimmt, welche der pro-Distro-Paketlisten einer Policy gilt)."""
from pathlib import Path


def detect_os_type() -> str:
    try:
        text = Path("/etc/os-release").read_text()
    except OSError:
        return ""

    values: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key] = value.strip().strip('"')

    os_id = values.get("ID", "")
    id_like = values.get("ID_LIKE", "")

    if os_id == "arch" or "arch" in id_like:
        return "archlinux"
    if os_id == "debian" or "debian" in id_like:
        return "debian"
    return os_id
