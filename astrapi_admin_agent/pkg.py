# astrapi_admin_agent/pkg.py
"""Paketverwaltung -- pacman (Arch) oder apt (Debian). Backend wird ueber
verfuegbare Binaries erkannt (robuster als os-release bei Derivaten)."""
import shutil
import subprocess
from pathlib import Path


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


def list_security_upgradable(backend: str) -> list[str]:
    """Teilmenge von list_upgradable(), die aus einer *-security-Suite
    stammt -- nur fuer apt (Debian) sinnvoll, siehe E-008. 'apt list
    --upgradable' zeigt die Suite direkt nach dem Paketnamen (z.B.
    'libssl3t64/stable-security', gegen ein echtes debian:trixie-slim
    verifiziert), kein zusaetzlicher Aufruf noetig -- reine
    Nachauswertung derselben Information. pacman/checkupdates kennt
    keine vergleichbare Kategorisierung, deshalb dort und bei
    unbekanntem Backend immer leer."""
    if backend != "apt":
        return []
    r = subprocess.run(["apt", "list", "--upgradable"], capture_output=True, text=True)
    result = []
    for ln in r.stdout.splitlines():
        if not ln.strip() or ln.startswith("Listing..."):
            continue
        name, _, rest = ln.partition("/")
        suite = rest.split(" ", 1)[0]
        if "security" in suite.lower():
            result.append(name)
    return result


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


def reboot_required(backend: str) -> bool:
    """Rein lesend, prueft den JETZT aktuellen Zustand (nach einem
    eventuellen upgrade_all()-Aufruf sinnvoll aufgerufen).

    apt (Debian): 'apt-get upgrade'/unattended-upgrades hinterlegen bei
    einem Kernel-/Bibliotheks-Update, das einen Neustart braucht, den
    Standard-Debian-Marker /var/run/reboot-required -- kein eigenes
    Parsing noetig.

    pacman (Arch): kennt keine vergleichbare Markierung. Ersatz-Heuristik:
    existiert das Modul-Verzeichnis des GERADE LAUFENDEN Kernels
    (uname -r) noch unter /usr/lib/modules/? pacman entfernt/ersetzt
    dieses Verzeichnis, sobald ein neueres 'linux'-Paket installiert wird
    -- fehlt es, laeuft noch der alte Kernel, obwohl bereits ein neuerer
    installiert ist."""
    if backend == "apt":
        return Path("/var/run/reboot-required").exists()
    if backend == "pacman":
        r = subprocess.run(["uname", "-r"], capture_output=True, text=True)
        running = r.stdout.strip()
        if not running:
            return False
        return not Path(f"/usr/lib/modules/{running}").exists()
    return False
