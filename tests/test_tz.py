"""tz.py -- T-321-ADMIN: Zeitzone + NTP-Sync ueber timedatectl setzen, nur
bei Abweichung vom Ist-Zustand (idempotent), best-effort wie
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
        status, detail = tz.ensure("Europe/Berlin")

    assert status == "ok"
    assert "bereits" in detail
    mock_run.assert_called_once()  # nur current(), kein set-timezone


def test_ensure_setzt_bei_abweichung():
    responses = [_fake_run("UTC\n"), _fake_run("")]
    with patch("astrapi_admin_agent.tz.subprocess.run", side_effect=responses) as mock_run:
        status, detail = tz.ensure("Europe/Berlin")

    assert status == "changed"
    assert detail == "UTC -> Europe/Berlin"
    assert mock_run.call_count == 2
    assert mock_run.call_args_list[1].args[0] == ["timedatectl", "set-timezone", "Europe/Berlin"]


def test_ensure_liefert_fehlerstatus_statt_zu_werfen():
    with patch(
        "astrapi_admin_agent.tz.subprocess.run",
        side_effect=[_fake_run("UTC\n"), subprocess.CalledProcessError(1, "timedatectl")],
    ):
        status, detail = tz.ensure("Europe/Berlin")

    assert status == "failed"
    assert "Fehler" in detail


def test_ensure_haengt_stderr_an_fehlermeldung_an():
    """Nachtrag: str(CalledProcessError) allein sagt nur "returned non-zero
    exit status 1" -- ohne stderr war auf dem betroffenen Host (T-327-ADMIN)
    nicht erkennbar, WARUM timedatectl scheiterte."""
    err = subprocess.CalledProcessError(1, "timedatectl", stderr="Failed to set time zone: NTP unit is masked.\n")
    with patch(
        "astrapi_admin_agent.tz.subprocess.run",
        side_effect=[_fake_run("UTC\n"), err],
    ):
        status, detail = tz.ensure("Europe/Berlin")

    assert status == "failed"
    assert "Failed to set time zone: NTP unit is masked." in detail


def test_ntp_active_liefert_true_bei_yes():
    with patch("astrapi_admin_agent.tz.subprocess.run", return_value=_fake_run("yes\n")):
        assert tz.ntp_active() is True


def test_ntp_active_liefert_false_bei_no():
    with patch("astrapi_admin_agent.tz.subprocess.run", return_value=_fake_run("no\n")):
        assert tz.ntp_active() is False


def test_ntp_active_liefert_none_bei_fehler():
    with patch("astrapi_admin_agent.tz.subprocess.run", side_effect=OSError("boom")):
        assert tz.ntp_active() is None


def test_ensure_ntp_ist_no_op_wenn_bereits_aktiv():
    with patch("astrapi_admin_agent.tz.subprocess.run", return_value=_fake_run("yes\n")) as mock_run:
        status, detail = tz.ensure_ntp()

    assert status == "ok"
    assert "bereits aktiv" in detail
    mock_run.assert_called_once()  # nur ntp_active(), kein set-ntp


def test_ensure_ntp_aktiviert_bei_abweichung():
    responses = [_fake_run("no\n"), _fake_run("")]
    with patch("astrapi_admin_agent.tz.subprocess.run", side_effect=responses) as mock_run:
        status, detail = tz.ensure_ntp()

    assert status == "changed"
    assert mock_run.call_count == 2
    assert mock_run.call_args_list[1].args[0] == ["timedatectl", "set-ntp", "true"]


def test_ensure_ntp_liefert_fehlerstatus_statt_zu_werfen():
    with patch(
        "astrapi_admin_agent.tz.subprocess.run",
        side_effect=[_fake_run("no\n"), subprocess.CalledProcessError(1, "timedatectl")],
    ):
        status, detail = tz.ensure_ntp()

    assert status == "failed"
    assert "Fehler" in detail


def test_ensure_ntp_haengt_stderr_an_fehlermeldung_an():
    err = subprocess.CalledProcessError(1, "timedatectl", stderr="Could not activate remote peer: timeout\n")
    with patch(
        "astrapi_admin_agent.tz.subprocess.run",
        side_effect=[_fake_run("no\n"), err],
    ):
        status, detail = tz.ensure_ntp()

    assert status == "failed"
    assert "Could not activate remote peer: timeout" in detail
