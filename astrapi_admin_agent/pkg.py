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


def install(names: list[str], backend: str) -> tuple[bool, str]:
    """Installiert alle fehlenden Pakete in EINEM Aufruf statt pro Paket --
    present ist risikoarm (keine Kaskadeneffekte), ein Batch-Aufruf reicht."""
    if not names:
        return True, ""
    if backend == "pacman":
        cmd = ["pacman", "-S", "--needed", "--noconfirm"] + names
    elif backend == "apt":
        cmd = ["apt-get", "install", "-y"] + names
    else:
        raise ValueError(f"Unbekanntes Paket-Backend: {backend}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr)


def remove_one(name: str, backend: str) -> tuple[bool, str]:
    """Entfernt EIN Paket -- absichtlich einzeln statt gebuendelt: ein
    Abhaengigkeits-Konflikt bei einem Paket soll die Entfernung der
    uebrigen nicht blockieren. Bewusst OHNE -Rs/-Rdd/--purge -- pacman/apt
    verweigern von selbst, wenn andere installierte Pakete davon
    abhaengen, und genau das ist das gewuenschte Sicherheitsnetz, kein
    Hindernis zum Umgehen."""
    if backend == "pacman":
        cmd = ["pacman", "-R", "--noconfirm", name]
    elif backend == "apt":
        cmd = ["apt-get", "remove", "-y", name]
    else:
        raise ValueError(f"Unbekanntes Paket-Backend: {backend}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr)
