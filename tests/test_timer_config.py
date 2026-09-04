"""timer_config.py -- E-011: der Agent gleicht bei jedem Poll seinen
eigenen systemd-Timer gegen den vom Server gewuenschten Wert ab (kein
Push, der Server kann dem Agenten nichts direkt aufzwingen)."""
from unittest.mock import MagicMock, patch

from astrapi_admin_agent import timer_config


def _redirect_dropin(monkeypatch, tmp_path):
    dropin_dir = tmp_path / "timer.d"
    dropin_path = dropin_dir / "override.conf"
    monkeypatch.setattr(timer_config, "DROPIN_DIR", dropin_dir)
    monkeypatch.setattr(timer_config, "DROPIN_PATH", dropin_path)
    return dropin_path


def test_apply_poll_interval_legt_dropin_beim_ersten_aufruf_an(monkeypatch, tmp_path):
    dropin_path = _redirect_dropin(monkeypatch, tmp_path)

    with patch("astrapi_admin_agent.timer_config.subprocess.run") as mock_run:
        timer_config.apply_poll_interval(30)

    assert dropin_path.exists()
    assert "OnUnitActiveSec=30min" in dropin_path.read_text()
    assert mock_run.call_count == 2


def test_apply_poll_interval_reset_zeile_kommt_vor_dem_eigentlichen_wert(monkeypatch, tmp_path):
    dropin_path = _redirect_dropin(monkeypatch, tmp_path)

    with patch("astrapi_admin_agent.timer_config.subprocess.run"):
        timer_config.apply_poll_interval(60)

    lines = [ln for ln in dropin_path.read_text().splitlines() if ln.startswith("OnUnitActiveSec=")]
    assert lines == ["OnUnitActiveSec=", "OnUnitActiveSec=60min"]


def test_apply_poll_interval_ruft_daemon_reload_und_timer_restart_auf(monkeypatch, tmp_path):
    _redirect_dropin(monkeypatch, tmp_path)

    with patch("astrapi_admin_agent.timer_config.subprocess.run") as mock_run:
        timer_config.apply_poll_interval(45)

    calls = [c.args[0] for c in mock_run.call_args_list]
    assert ["systemctl", "daemon-reload"] in calls
    assert ["systemctl", "restart", "astrapi-admin-agent.timer"] in calls


def test_apply_poll_interval_unveraenderter_wert_ist_ein_no_op(monkeypatch, tmp_path):
    _redirect_dropin(monkeypatch, tmp_path)

    with patch("astrapi_admin_agent.timer_config.subprocess.run") as mock_run:
        timer_config.apply_poll_interval(15)
        mock_run.reset_mock()
        timer_config.apply_poll_interval(15)

    mock_run.assert_not_called()


def test_apply_poll_interval_geaenderter_wert_schreibt_erneut(monkeypatch, tmp_path):
    dropin_path = _redirect_dropin(monkeypatch, tmp_path)

    with patch("astrapi_admin_agent.timer_config.subprocess.run") as mock_run:
        timer_config.apply_poll_interval(15)
        mock_run.reset_mock()
        timer_config.apply_poll_interval(120)

    assert "OnUnitActiveSec=120min" in dropin_path.read_text()
    assert mock_run.call_count == 2


def test_apply_poll_interval_fehler_bei_subprocess_bricht_nicht_ab(monkeypatch, tmp_path):
    _redirect_dropin(monkeypatch, tmp_path)

    with patch("astrapi_admin_agent.timer_config.subprocess.run", side_effect=OSError("boom")):
        timer_config.apply_poll_interval(30)  # darf keine Exception werfen


def test_enable_now_ruft_systemctl_enable_now_auf():
    with patch("astrapi_admin_agent.timer_config.subprocess.run") as mock_run:
        timer_config.enable_now()

    mock_run.assert_called_once_with(
        ["systemctl", "enable", "--now", "astrapi-admin-agent.timer"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_enable_now_wirft_bei_fehler_weiter():
    """Anders als apply_poll_interval() ist enable_now() NICHT best-effort
    -- der Aufrufer (cmd_pair) entscheidet selbst, wie er einen Fehler
    meldet (Warnung statt stillem Schlucken, siehe cli.py)."""
    import subprocess

    with patch(
        "astrapi_admin_agent.timer_config.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "systemctl"),
    ):
        try:
            timer_config.enable_now()
            raised = False
        except subprocess.CalledProcessError:
            raised = True

    assert raised


def _mock_list_timers_run(stdout: str):
    result = MagicMock()
    result.stdout = stdout
    return result


def test_next_run_at_liefert_lesbaren_zeitstempel():
    stdout = '[{"next":1788550946500031,"left":1788550946500031,"last":1788550570373266,"passed":618354382073,"unit":"astrapi-admin-agent.timer","activates":"astrapi-admin-agent.service"}]'
    with patch("astrapi_admin_agent.timer_config.subprocess.run", return_value=_mock_list_timers_run(stdout)):
        result = timer_config.next_run_at()

    from datetime import datetime

    assert result == datetime.fromtimestamp(1788550946500031 / 1_000_000).strftime("%Y-%m-%d %H:%M:%S")


def test_next_run_at_liefert_none_ohne_geplanten_lauf():
    """T-303-ADMIN-Fall: ein nicht enabled/nie ausgeloester Timer hat
    kein 'next' -- lieber None als ein irrefuehrender geschaetzter
    Zeitpunkt."""
    stdout = '[{"next":0,"left":0,"last":0,"passed":0,"unit":"astrapi-admin-agent.timer","activates":"astrapi-admin-agent.service"}]'
    with patch("astrapi_admin_agent.timer_config.subprocess.run", return_value=_mock_list_timers_run(stdout)):
        assert timer_config.next_run_at() is None


def test_next_run_at_leere_liste_liefert_none():
    with patch("astrapi_admin_agent.timer_config.subprocess.run", return_value=_mock_list_timers_run("[]")):
        assert timer_config.next_run_at() is None


def test_next_run_at_fehler_bei_subprocess_liefert_none():
    with patch("astrapi_admin_agent.timer_config.subprocess.run", side_effect=OSError("boom")):
        assert timer_config.next_run_at() is None


def test_next_run_at_kaputtes_json_liefert_none():
    with patch("astrapi_admin_agent.timer_config.subprocess.run", return_value=_mock_list_timers_run("nicht json")):
        assert timer_config.next_run_at() is None
