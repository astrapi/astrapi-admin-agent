"""cli.py: pair/apply muessen als root laufen -- die Pruefung muss VOR
jeder Seitenwirkung greifen (insbesondere vor dem Einloesen des
einmaligen Pairing-Codes beim Server, siehe cmd_pair)."""
from types import SimpleNamespace
from unittest.mock import patch

from astrapi_admin_agent import cli


def _pair_args():
    return SimpleNamespace(
        server_url="http://admin.simpsons.lan:5005",
        pairing_code="abc123",
        hostname="",
        os_type="",
    )


def test_cmd_pair_bricht_ohne_root_ab_vor_dem_pairing_aufruf():
    with patch("astrapi_admin_agent.cli.os.geteuid", return_value=1000), \
         patch("astrapi_admin_agent.cli.ApiClient.pair") as mock_pair:
        rc = cli.cmd_pair(_pair_args())

    assert rc == 1
    mock_pair.assert_not_called()


def test_cmd_pair_laeuft_als_root_weiter():
    with patch("astrapi_admin_agent.cli.os.geteuid", return_value=0), \
         patch("astrapi_admin_agent.cli.ApiClient.pair", return_value={"host_id": "1", "host_token": "tok"}), \
         patch("astrapi_admin_agent.cli.cfgmod.load", return_value={}), \
         patch("astrapi_admin_agent.cli.cfgmod.save") as mock_save, \
         patch("astrapi_admin_agent.cli.cfgmod.config_path", return_value="/etc/astrapi-admin/config.json"), \
         patch("astrapi_admin_agent.cli.timer_config.enable_now") as mock_enable:
        rc = cli.cmd_pair(_pair_args())

    assert rc == 0
    mock_save.assert_called_once()
    mock_enable.assert_called_once()


def test_cmd_pair_aktiviert_den_timer_dauerhaft():
    """T-303-ADMIN: ohne 'systemctl enable' (nur 'start') ueberlebt der
    Timer keinen Reboot -- weder Paket noch Agent riefen das bisher an
    irgendeiner Stelle auf."""
    with patch("astrapi_admin_agent.cli.os.geteuid", return_value=0), \
         patch("astrapi_admin_agent.cli.ApiClient.pair", return_value={"host_id": "1", "host_token": "tok"}), \
         patch("astrapi_admin_agent.cli.cfgmod.load", return_value={}), \
         patch("astrapi_admin_agent.cli.cfgmod.save"), \
         patch("astrapi_admin_agent.cli.cfgmod.config_path", return_value="/etc/astrapi-admin/config.json"), \
         patch("astrapi_admin_agent.cli.timer_config.enable_now") as mock_enable:
        cli.cmd_pair(_pair_args())

    mock_enable.assert_called_once_with()


def test_cmd_pair_fehlschlag_beim_timer_aktivieren_bricht_pairing_nicht_ab():
    """Pairing selbst (Konfiguration ist gespeichert, Host ist beim Server
    bekannt) darf nicht an einem fehlgeschlagenen Timer-Enable scheitern --
    der Nutzer bekommt stattdessen eine Warnung und kann manuell
    nachholen."""
    with patch("astrapi_admin_agent.cli.os.geteuid", return_value=0), \
         patch("astrapi_admin_agent.cli.ApiClient.pair", return_value={"host_id": "1", "host_token": "tok"}), \
         patch("astrapi_admin_agent.cli.cfgmod.load", return_value={}), \
         patch("astrapi_admin_agent.cli.cfgmod.save"), \
         patch("astrapi_admin_agent.cli.cfgmod.config_path", return_value="/etc/astrapi-admin/config.json"), \
         patch("astrapi_admin_agent.cli.timer_config.enable_now", side_effect=OSError("boom")):
        rc = cli.cmd_pair(_pair_args())

    assert rc == 0


def test_cmd_apply_bricht_ohne_root_ab_vor_dem_config_laden():
    with patch("astrapi_admin_agent.cli.os.geteuid", return_value=1000), \
         patch("astrapi_admin_agent.cli.cfgmod.load") as mock_load:
        rc = cli.cmd_apply(SimpleNamespace())

    assert rc == 1
    mock_load.assert_not_called()


def _mock_apply_run(policy: dict, upgradable: list[str] | None = None, security_upgradable: list[str] | None = None):
    """Gemeinsames Mock-Setup fuer cmd_apply()-Tests -- root, Config,
    ApiClient, Backend-Erkennung, Policy-Konvergenz sind alle gemockt,
    nur pkg.list_upgradable()/list_security_upgradable()/upgrade_all()
    bleiben testrelevant. timer_config.apply_poll_interval() ist ebenfalls
    gemockt -- sonst wuerde jeder dieser Tests real versuchen, unter
    /etc/systemd/system/ zu schreiben und systemctl aufzurufen (E-011).
    usersmod.inventory() ebenfalls gemockt (E-012) -- rein lesend zwar
    unbedenklich, aber konsistent mit demselben Vorsichtsprinzip."""
    return (
        patch("astrapi_admin_agent.cli.os.geteuid", return_value=0),
        patch("astrapi_admin_agent.cli.cfgmod.load", return_value={"host_token": "tok", "server_url": "http://x"}),
        patch("astrapi_admin_agent.cli.ApiClient.get_policy", return_value=policy),
        patch("astrapi_admin_agent.cli.ApiClient.report", return_value={"ok": True}) ,
        patch("astrapi_admin_agent.cli.pkg.detect_backend", return_value="apt"),
        patch("astrapi_admin_agent.cli.pkg.list_upgradable", return_value=upgradable or []),
        patch("astrapi_admin_agent.cli.pkg.list_security_upgradable", return_value=security_upgradable or []),
        patch(
            "astrapi_admin_agent.cli.applymod.apply_policy",
            return_value={"packages": [], "services": [], "config_files": [], "users": []},
        ),
        patch("astrapi_admin_agent.cli.timer_config.apply_poll_interval"),
        patch("astrapi_admin_agent.cli.usersmod.inventory", return_value=[]),
        patch("astrapi_admin_agent.cli.timer_config.next_run_at", return_value="2026-09-04 22:00:00"),
    )


def test_cmd_apply_ohne_pending_action_ruft_upgrade_all_nicht_auf():
    patches = _mock_apply_run({"conflicts": []})
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], \
         patch("astrapi_admin_agent.cli.pkg.upgrade_all") as mock_upgrade:
        rc = cli.cmd_apply(SimpleNamespace())

    assert rc == 0
    mock_upgrade.assert_not_called()


def test_cmd_apply_mit_pending_action_ruft_upgrade_all_auf():
    policy = {"conflicts": [], "pending_action": "update"}
    patches = _mock_apply_run(policy, upgradable=["htop", "vim"])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], \
         patch("astrapi_admin_agent.cli.pkg.upgrade_all", return_value=(True, "upgraded 3 packages")) as mock_upgrade, \
         patch("astrapi_admin_agent.cli.ApiClient.report") as mock_report:
        rc = cli.cmd_apply(SimpleNamespace())

    assert rc == 0
    mock_upgrade.assert_called_once_with("apt")
    sent_details = mock_report.call_args[0][2]
    assert sent_details["update_result"] == {
        "ok": True,
        "detail": "upgraded 3 packages",
        "packages": ["htop", "vim"],
    }


def test_cmd_apply_fehlgeschlagenes_update_setzt_status_error():
    policy = {"conflicts": [], "pending_action": "update"}
    patches = _mock_apply_run(policy)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], \
         patch("astrapi_admin_agent.cli.pkg.upgrade_all", return_value=(False, "network error")), \
         patch("astrapi_admin_agent.cli.ApiClient.report") as mock_report:
        rc = cli.cmd_apply(SimpleNamespace())

    assert rc == 1
    sent_status = mock_report.call_args[0][0]
    assert sent_status == "error"


def test_cmd_apply_meldet_updates_available_immer():
    policy = {"conflicts": []}
    patches = _mock_apply_run(policy, upgradable=["htop", "vim"])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], \
         patch("astrapi_admin_agent.cli.ApiClient.report") as mock_report:
        cli.cmd_apply(SimpleNamespace())

    sent_details = mock_report.call_args[0][2]
    assert sent_details["updates_available"] == 2


def test_cmd_apply_meldet_security_updates_available_bei_apt():
    policy = {"conflicts": []}
    patches = _mock_apply_run(policy, upgradable=["htop", "libssl3"], security_upgradable=["libssl3"])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], \
         patch("astrapi_admin_agent.cli.ApiClient.report") as mock_report:
        cli.cmd_apply(SimpleNamespace())

    sent_details = mock_report.call_args[0][2]
    assert sent_details["security_updates_available"] == 1


def test_cmd_apply_kein_security_feld_ohne_apt_backend():
    policy = {"conflicts": []}
    patches = _mock_apply_run(policy, upgradable=["htop"])
    with patches[0], patches[1], patches[2], patches[3], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], \
         patch("astrapi_admin_agent.cli.pkg.detect_backend", return_value="pacman"), \
         patch("astrapi_admin_agent.cli.ApiClient.report") as mock_report:
        cli.cmd_apply(SimpleNamespace())

    sent_details = mock_report.call_args[0][2]
    assert "security_updates_available" not in sent_details


def test_cmd_apply_meldet_paketlisten_fuer_die_vorschau():
    policy = {"conflicts": []}
    patches = _mock_apply_run(policy, upgradable=["htop", "libssl3"], security_upgradable=["libssl3"])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], \
         patch("astrapi_admin_agent.cli.ApiClient.report") as mock_report:
        cli.cmd_apply(SimpleNamespace())

    sent_details = mock_report.call_args[0][2]
    assert sent_details["upgradable_packages"] == ["htop", "libssl3"]
    assert sent_details["security_upgradable_packages"] == ["libssl3"]


def test_cmd_apply_update_result_enthaelt_angewandte_pakete():
    policy = {"conflicts": [], "pending_action": "update"}
    patches = _mock_apply_run(policy, upgradable=["htop", "vim"])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], \
         patch("astrapi_admin_agent.cli.pkg.upgrade_all", return_value=(True, "upgraded")), \
         patch("astrapi_admin_agent.cli.ApiClient.report") as mock_report:
        cli.cmd_apply(SimpleNamespace())

    sent_details = mock_report.call_args[0][2]
    assert sent_details["update_result"]["packages"] == ["htop", "vim"]
