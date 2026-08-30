"""services.py: apply_state() darf nur die tatsaechliche Differenz zum
Zielzustand nachziehen, nicht blind enable/start bei jedem Lauf."""
from unittest.mock import patch

from astrapi_admin_agent import services


def _fake_run(returncode=0):
    class _Result:
        pass

    r = _Result()
    r.returncode = returncode
    r.stdout = ""
    r.stderr = ""
    return r


def test_bereits_im_zielzustand_ruft_keine_aktion_auf():
    with patch("astrapi_admin_agent.services.is_enabled", return_value=True), \
         patch("astrapi_admin_agent.services.is_active", return_value=True), \
         patch("astrapi_admin_agent.services.subprocess.run") as mock_run:
        ok, detail = services.apply_state("nginx", "enabled_started")

    assert ok is True
    assert detail == "bereits im Zielzustand"
    mock_run.assert_not_called()


def test_enabled_started_zieht_nur_die_fehlende_aktion_nach():
    with patch("astrapi_admin_agent.services.is_enabled", return_value=False), \
         patch("astrapi_admin_agent.services.is_active", return_value=True), \
         patch("astrapi_admin_agent.services.subprocess.run", return_value=_fake_run()) as mock_run:
        ok, detail = services.apply_state("nginx", "enabled_started")

    assert ok is True
    assert mock_run.call_count == 1
    assert mock_run.call_args[0][0] == ["systemctl", "enable", "nginx"]


def test_disabled_stopped_disabled_und_stoppt():
    with patch("astrapi_admin_agent.services.is_enabled", return_value=True), \
         patch("astrapi_admin_agent.services.is_active", return_value=True), \
         patch("astrapi_admin_agent.services.subprocess.run", return_value=_fake_run()) as mock_run:
        ok, _ = services.apply_state("nginx", "disabled_stopped")

    calls = [c.args[0] for c in mock_run.call_args_list]
    assert ["systemctl", "disable", "nginx"] in calls
    assert ["systemctl", "stop", "nginx"] in calls


def test_started_laesst_enabled_status_unangetastet():
    with patch("astrapi_admin_agent.services.is_enabled", return_value=False), \
         patch("astrapi_admin_agent.services.is_active", return_value=False), \
         patch("astrapi_admin_agent.services.subprocess.run", return_value=_fake_run()) as mock_run:
        services.apply_state("nginx", "started")

    calls = [c.args[0] for c in mock_run.call_args_list]
    assert ["systemctl", "enable", "nginx"] not in calls
    assert ["systemctl", "start", "nginx"] in calls


def test_bricht_bei_fehlgeschlagener_aktion_ab():
    with patch("astrapi_admin_agent.services.is_enabled", return_value=False), \
         patch("astrapi_admin_agent.services.is_active", return_value=False), \
         patch("astrapi_admin_agent.services.subprocess.run", return_value=_fake_run(returncode=1)) as mock_run:
        ok, detail = services.apply_state("nginx", "enabled_started")

    assert ok is False
    assert mock_run.call_count == 1


def test_unbekannter_zielzustand():
    ok, detail = services.apply_state("nginx", "quantum_superposition")
    assert ok is False
    assert "Unbekannter Zielzustand" in detail
