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


def test_list_upgradable_pacman_ohne_checkupdates_liefert_leere_liste(monkeypatch):
    monkeypatch.setattr(pkg.shutil, "which", lambda name: None)
    with patch("astrapi_admin_agent.pkg.subprocess.run") as mock_run:
        assert pkg.list_upgradable("pacman") == []
    mock_run.assert_not_called()


def test_list_upgradable_pacman_parst_paketnamen(monkeypatch):
    monkeypatch.setattr(pkg.shutil, "which", lambda name: "/usr/bin/checkupdates")
    stdout = "htop 3.3.0-1 -> 3.4.0-1\nvim 9.0-1 -> 9.1-1\n"
    with patch("astrapi_admin_agent.pkg.subprocess.run", return_value=_fake_run(0, stdout=stdout)):
        assert pkg.list_upgradable("pacman") == ["htop", "vim"]


def test_list_upgradable_pacman_keine_updates_ist_kein_fehler(monkeypatch):
    monkeypatch.setattr(pkg.shutil, "which", lambda name: "/usr/bin/checkupdates")
    with patch("astrapi_admin_agent.pkg.subprocess.run", return_value=_fake_run(2, stdout="")):
        assert pkg.list_upgradable("pacman") == []


def test_list_upgradable_apt_refresht_index_und_parst_liste():
    calls = []

    def _fake(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["apt-get", "update"]:
            return _fake_run(0)
        return _fake_run(0, stdout="Listing...\nhtop/stable 3.3.0 amd64 [upgradable from: 3.2.0]\n")

    with patch("astrapi_admin_agent.pkg.subprocess.run", side_effect=_fake):
        result = pkg.list_upgradable("apt")

    assert result == ["htop"]
    assert calls[0] == ["apt-get", "update"]


def test_list_upgradable_unbekanntes_backend_liefert_leere_liste():
    assert pkg.list_upgradable("") == []


def test_upgrade_all_pacman_kommando():
    with patch("astrapi_admin_agent.pkg.subprocess.run", return_value=_fake_run(0)) as mock_run:
        ok, _ = pkg.upgrade_all("pacman")
    assert ok is True
    assert mock_run.call_args[0][0] == ["pacman", "-Syu", "--noconfirm"]


def test_upgrade_all_apt_kommando():
    with patch("astrapi_admin_agent.pkg.subprocess.run", return_value=_fake_run(0)) as mock_run:
        pkg.upgrade_all("apt")
    assert mock_run.call_args[0][0] == ["apt-get", "upgrade", "-y"]


def test_upgrade_all_meldet_fehlschlag():
    with patch("astrapi_admin_agent.pkg.subprocess.run", return_value=_fake_run(1, stderr="boom")):
        ok, detail = pkg.upgrade_all("apt")
    assert ok is False
    assert "boom" in detail


def test_upgrade_all_unbekanntes_backend_wirft_value_error():
    with pytest.raises(ValueError):
        pkg.upgrade_all("yum")
