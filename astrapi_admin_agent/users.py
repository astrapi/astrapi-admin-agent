# astrapi_admin_agent/users.py
"""OS-Nutzerkonten -- analog zu files.py/services.py: idempotente
Durchsetzung nur der Differenz zum Ziel, klare (status, detail)-
Rueckgabe. Bewusst KEIN Passwort-Management (SSH-Key-basierter Zugriff
wie im gesamten astrapi-Oekosystem ueblich) -- /etc/shadow wird nie
angefasst.

Sicherheitsregel (siehe [[E-012]]): ein per Bestandsaufnahme
entdeckter Account wird NIE automatisch "verwaltet" -- nur ein Account,
den DIESER Agent selbst per useradd angelegt hat (managed_users im
lokalen State, siehe state.py), darf spaeter per action=absent wieder
per 'userdel -r' geloescht werden. Ein vorbestehender, fremder Account
wird bei action=absent nie geloescht (remove_if_managed() faellt dann
auf skipped_conflict zurueck, analog zu files.remove_if_managed())."""
import grp
import pwd
import shutil
import subprocess
from pathlib import Path

from astrapi_admin_agent import files, state

UID_MIN = 1000  # System-/Dienstkonten (uid < 1000) werden nie erfasst


def _sudo_group(backend: str) -> str:
    return "sudo" if backend == "apt" else "wheel"


def _is_group_member(username: str, group: str) -> bool:
    try:
        return username in grp.getgrnam(group).gr_mem
    except KeyError:
        return False


def _group_names(username: str) -> list[str]:
    return sorted(g.gr_name for g in grp.getgrall() if username in g.gr_mem)


def _primary_group(username: str) -> str:
    pw = pwd.getpwnam(username)
    return grp.getgrgid(pw.pw_gid).gr_name


def user_exists(username: str) -> bool:
    try:
        pwd.getpwnam(username)
        return True
    except KeyError:
        return False


def inventory() -> list[dict]:
    """Rein lesend, wird IMMER aufgerufen (wie pkg.list_upgradable()) --
    unabhaengig davon, ob je eine Nutzer-Policy existiert. Meldet NIE
    SSH-Key-INHALTE, nur ob welche hinterlegt sind -- fuer die reine
    Bestandsaufnahme nicht relevant, haelt den Report klein."""
    managed = set(state.load().get("managed_users", []))
    out = []
    for entry in pwd.getpwall():
        if entry.pw_uid < UID_MIN:
            continue
        groups = _group_names(entry.pw_name)
        out.append(
            {
                "username": entry.pw_name,
                "uid": entry.pw_uid,
                "shell": entry.pw_shell,
                "sudo": any(g in ("sudo", "wheel") for g in groups),
                "has_ssh_keys": (Path(entry.pw_dir) / ".ssh" / "authorized_keys").exists(),
                "managed": entry.pw_name in managed,
            }
        )
    return out


def enforce(entry: dict, backend: str) -> tuple[str, str]:
    """Legt den Account bei Bedarf an (useradd -m), gleicht Shell,
    sudo/wheel-Mitgliedschaft und SSH-Keys ab."""
    username = entry["username"]
    shell = entry.get("shell") or "/bin/bash"
    changed = []

    if not user_exists(username):
        r = subprocess.run(["useradd", "-m", "-s", shell, username], capture_output=True, text=True)
        if r.returncode != 0:
            return "failed", (r.stdout + r.stderr).strip()
        changed.append("angelegt")
    elif pwd.getpwnam(username).pw_shell != shell:
        r = subprocess.run(["usermod", "-s", shell, username], capture_output=True, text=True)
        if r.returncode != 0:
            return "failed", (r.stdout + r.stderr).strip()
        changed.append("Shell aktualisiert")

    sudo_group = _sudo_group(backend)
    is_sudo = _is_group_member(username, sudo_group)
    want_sudo = bool(entry.get("sudo"))
    if want_sudo and not is_sudo:
        r = subprocess.run(["usermod", "-aG", sudo_group, username], capture_output=True, text=True)
        if r.returncode != 0:
            return "failed", (r.stdout + r.stderr).strip()
        changed.append(f"zu '{sudo_group}' hinzugefügt")
    elif not want_sudo and is_sudo:
        r = subprocess.run(["gpasswd", "-d", username, sudo_group], capture_output=True, text=True)
        if r.returncode != 0:
            return "failed", (r.stdout + r.stderr).strip()
        changed.append(f"aus '{sudo_group}' entfernt")

    ssh_keys = entry.get("ssh_keys") or []
    desired = "\n".join(ssh_keys) + ("\n" if ssh_keys else "")
    home = Path(pwd.getpwnam(username).pw_dir)
    ssh_dir = home / ".ssh"
    keys_path = ssh_dir / "authorized_keys"
    current = keys_path.read_text() if keys_path.exists() else None
    if current != desired:
        try:
            ssh_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            group = _primary_group(username)
            shutil.chown(ssh_dir, user=username, group=group)
            files.atomic_write(keys_path, desired, 0o600, username, group)
        except OSError as e:
            return "failed", str(e)
        changed.append("SSH-Keys aktualisiert")

    if not changed:
        return "ok", "bereits im Zielzustand"
    return "changed", ", ".join(changed)


def remove_if_managed(username: str, managed_users: list[str]) -> tuple[str, str]:
    """'userdel -r' NUR wenn der Account von diesem Agenten selbst
    angelegt wurde (username in managed_users) -- sonst skipped_conflict,
    analog zu files.remove_if_managed()."""
    if not user_exists(username):
        return "ok", "bereits entfernt"
    if username not in managed_users:
        return "skipped_conflict", f"'{username}' wurde nicht von astrapi-admin angelegt -- nicht gelöscht"
    r = subprocess.run(["userdel", "-r", username], capture_output=True, text=True)
    if r.returncode != 0:
        return "failed", (r.stdout + r.stderr).strip()
    return "changed", f"'{username}' entfernt (inkl. Home-Verzeichnis)"
