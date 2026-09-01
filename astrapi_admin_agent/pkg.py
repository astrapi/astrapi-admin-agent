# astrapi_admin_agent/pkg.py
"""Paketverwaltung -- pacman (Arch) oder apt (Debian). Backend wird ueber
verfuegbare Binaries erkannt (robuster als os-release bei Derivaten)."""
import shutil
import subprocess


def detect_backend() -> str:
    if shutil.which("pacman"):
        return "pacman"
    if shutil.which("apt-get"):
        return "apt"
    return ""


def is_installed(name: str, backend: str) -> bool:
    if backend == "pacman":
        return subprocess.run(["pacman", "-Q", name], capture_output=True).returncode == 0
    if backend == "apt":
        r = subprocess.run(["dpkg", "-s", name], capture_output=True)
        return r.returncode == 0 and b"Status: install ok installed" in r.stdout
    raise ValueError(f"Unbekanntes Paket-Backend: {backend}")


def list_upgradable(backend: str) -> list[str]:
    """Rein lesend, veraendert keinen Systemzustand -- sicher fuer jeden
    apply()-Zyklus, unabhaengig davon, ob je ein Update angestossen wird.

    apt:    'apt-get update' (Index-Refresh, KEIN Install) gefolgt von
            'apt list --upgradable'.
    pacman: 'checkupdates' (aus pacman-contrib) -- synct eine eigene
            TEMPORAERE Kopie der Sync-DB, ruehrt /var/lib/pacman nicht
            an, deshalb unbedenklich fuer periodische Checks (anders
            als ein rohes 'pacman -Sy'). Fehlt das Binary (pacman-contrib
            nicht installiert), liefert das schlicht eine leere Liste
            statt eines Fehlers -- 'nicht pruefbar', kein Fehlerfall."""
    if backend == "pacman":
        if not shutil.which("checkupdates"):
            return []
        r = subprocess.run(["checkupdates"], capture_output=True, text=True)
        return [ln.split(" ")[0] for ln in r.stdout.splitlines() if ln.strip()]
    if backend == "apt":
        subprocess.run(["apt-get", "update"], capture_output=True)
        r = subprocess.run(["apt", "list", "--upgradable"], capture_output=True, text=True)
        return [
            ln.split("/")[0]
            for ln in r.stdout.splitlines()
            if ln.strip() and not ln.startswith("Listing...")
        ]
    return []


def upgrade_all(backend: str) -> tuple[bool, str]:
    """Echtes Update -- wird vom Aufrufer NUR ausgefuehrt, wenn der
    Server das explizit ueber pending_action angefordert hat, nie
    automatisch als Teil der normalen Policy-Konvergenz (siehe E-007:
    bewusst eine einmalige, von Hand ausgeloeste Aktion pro Host, kein
    Policy-getriebenes Auto-Update wie das mit E-004 abgeschaffte
    Verhalten)."""
    if backend == "pacman":
        cmd = ["pacman", "-Syu", "--noconfirm"]
    elif backend == "apt":
        cmd = ["apt-get", "upgrade", "-y"]
    else:
        raise ValueError(f"Unbekanntes Paket-Backend: {backend}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr)
