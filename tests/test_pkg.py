"""pkg.py: Backend-Erkennung und reiner Installations-Check (kein
Installieren/Entfernen mehr durch den Agenten, siehe E-004)."""
from unittest.mock import patch

import pytest

from astrapi_admin_agent import pkg


def _fake_run(returncode=0, stdout="", stderr=""):
    class _Result:
        pass

    r = _Result()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


def test_detect_backend_bevorzugt_pacman(monkeypatch):
    monkeypatch.setattr(pkg.shutil, "which", lambda name: "/usr/bin/pacman" if name == "pacman" else None)
    assert pkg.detect_backend() == "pacman"


def test_detect_backend_apt_ohne_pacman(monkeypatch):
    monkeypatch.setattr(pkg.shutil, "which", lambda name: "/usr/bin/apt-get" if name == "apt-get" else None)
    assert pkg.detect_backend() == "apt"


def test_detect_backend_leer_ohne_bekannten_manager(monkeypatch):
    monkeypatch.setattr(pkg.shutil, "which", lambda name: None)
    assert pkg.detect_backend() == ""


def test_is_installed_pacman_prueft_ueber_pacman_q():
    with patch("astrapi_admin_agent.pkg.subprocess.run", return_value=_fake_run(0)) as mock_run:
        assert pkg.is_installed("htop", "pacman") is True
    assert mock_run.call_args[0][0] == ["pacman", "-Q", "htop"]


def test_is_installed_apt_prueft_status_zeile():
    stdout = b"Package: htop\nStatus: install ok installed\n"
    with patch("astrapi_admin_agent.pkg.subprocess.run", return_value=_fake_run(0, stdout=stdout)):
        assert pkg.is_installed("htop", "apt") is True


def test_is_installed_apt_false_bei_removed_status():
    stdout = b"Package: htop\nStatus: deinstall ok config-files\n"
    with patch("astrapi_admin_agent.pkg.subprocess.run", return_value=_fake_run(0, stdout=stdout)):
        assert pkg.is_installed("htop", "apt") is False


def test_unbekanntes_backend_wirft_value_error():
    with pytest.raises(ValueError):
        pkg.is_installed("htop", "yum")
