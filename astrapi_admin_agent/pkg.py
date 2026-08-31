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
