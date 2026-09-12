"""tz.py -- T-321-ADMIN: Zeitzone ueber timedatectl setzen, nur bei
Abweichung vom Ist-Zustand (idempotent), best-effort wie
pkg.reboot_required()."""
import subprocess
from unittest.mock import patch

from astrapi_admin_agent import tz


def _fake_run(stdout=""):
    class _Result:
        pass

    r = _Result()
    r.stdout = stdout
    return r


def test_current_liefert_getrimmte_ausgabe():
    with patch("astrapi_admin_agent.tz.subprocess.run", return_value=_fake_run("Europe/Berlin\n")):
        assert tz.current() == "Europe/Berlin"


def test_current_liefert_none_bei_leerer_ausgabe():
    with patch("astrapi_admin_agent.tz.subprocess.run", return_value=_fake_run("")):
        assert tz.current() is None


def test_current_liefert_none_bei_fehler():
    with patch("astrapi_admin_agent.tz.subprocess.run", side_effect=OSError("boom")):
        assert tz.current() is None


def test_ensure_ist_no_op_wenn_bereits_gesetzt():
    with patch("astrapi_admin_agent.tz.subprocess.run", return_value=_fake_run("Europe/Berlin\n")) as mock_run:
        changed, detail = tz.ensure("Europe/Berlin")

    assert changed is False
    assert "bereits" in detail
    mock_run.assert_called_once()  # nur current(), kein set-timezone


def test_ensure_setzt_bei_abweichung():
    responses = [_fake_run("UTC\n"), _fake_run("")]
    with patch("astrapi_admin_agent.tz.subprocess.run", side_effect=responses) as mock_run:
        changed, detail = tz.ensure("Europe/Berlin")

    assert changed is True
    assert detail == "UTC -> Europe/Berlin"
    assert mock_run.call_count == 2
    assert mock_run.call_args_list[1].args[0] == ["timedatectl", "set-timezone", "Europe/Berlin"]


def test_ensure_liefert_fehlertext_statt_zu_werfen():
    with patch(
        "astrapi_admin_agent.tz.subprocess.run",
        side_effect=[_fake_run("UTC\n"), subprocess.CalledProcessError(1, "timedatectl")],
    ):
        changed, detail = tz.ensure("Europe/Berlin")

    assert changed is False
    assert "Fehler" in detail
