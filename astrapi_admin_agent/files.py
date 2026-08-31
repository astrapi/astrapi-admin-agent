# astrapi_admin_agent/files.py
"""Config-Datei-Durchsetzung.

Fremd besessene Pfade (von einem Paket verwaltet, z.B. /etc/vimrc) werden
per Default NIE ueberschrieben -- genau das Problem, das bei den
vim-config-Paketen heute schon aufgetreten ist, hier von Anfang an
eingeplant. Ein Policy-/Template-Eintrag kann das ueber `force: true`
explizit aufheben (Nutzerentscheidung: eigenes, single-owner Setup, ein
Template wie "Caddy" bringt bewusst eine eigene Caddyfile mit und soll
die vom Paket mitgelieferte Platzhalter-Datei ersetzen duerfen) -- das ist
ein bewusster, expliziter Opt-out pro Datei, keine Abschaffung der
Schutzregel selbst (Default bleibt geschuetzt). Geloescht wird bei
action=absent weiterhin nur, was astrapi-admin selbst angelegt hat
(managed_paths im lokalen State, siehe state.py) -- nie eine fremde
oder vorbestehende Datei, `force` gilt nur fuer action=enforce."""
import grp
import os
import pwd
import shutil
import subprocess
from pathlib import Path


def is_package_owned(path: str) -> bool:
    if shutil.which("pacman"):
        return subprocess.run(["pacman", "-Qo", path], capture_output=True).returncode == 0
    if shutil.which("dpkg"):
        return subprocess.run(["dpkg", "-S", path], capture_output=True).returncode == 0
    return False


def _current_mode(path: Path) -> str:
    return oct(path.stat().st_mode & 0o777)[2:].zfill(4)


def _current_owner_group(path: Path) -> tuple[str, str]:
    st = path.stat()
    return pwd.getpwuid(st.st_uid).pw_name, grp.getgrgid(st.st_gid).gr_name


def atomic_write(path: Path, content: str, mode: int, owner: str, group: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        os.write(fd, content.encode())
    finally:
        os.close(fd)
    os.replace(tmp, path)
    shutil.chown(path, user=owner, group=group)


def enforce(cf: dict) -> tuple[str, str]:
    """Gibt (status, detail) zurueck. status in
    {'ok', 'changed', 'skipped_conflict', 'failed'}."""
    path = Path(cf["path"])

    if path.exists() and is_package_owned(str(path)) and not cf.get("force"):
        return "skipped_conflict", f"{path} wird von einem Paket verwaltet -- nicht überschrieben"

    mode = int(cf.get("mode", "0644"), 8)
    owner = cf.get("owner", "root")
    group = cf.get("group", "root")
    content = cf.get("content", "")

    if path.exists():
        try:
            unchanged = (
                path.read_text() == content
                and _current_mode(path) == oct(mode)[2:].zfill(4)
                and _current_owner_group(path) == (owner, group)
            )
        except OSError as e:
            return "failed", str(e)
        if unchanged:
            return "ok", "unverändert"

    try:
        atomic_write(path, content, mode, owner, group)
    except OSError as e:
        return "failed", str(e)
    return "changed", f"{path} geschrieben"


def remove_if_managed(path: str, managed_paths: list[str]) -> tuple[str, str]:
    if path not in managed_paths:
        return "skipped_conflict", f"{path} wurde nicht von astrapi-admin angelegt -- nicht gelöscht"
    p = Path(path)
    if not p.exists():
        return "ok", "bereits entfernt"
    try:
        p.unlink()
    except OSError as e:
        return "failed", str(e)
    return "changed", f"{path} entfernt"
