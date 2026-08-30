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
         patch("astrapi_admin_agent.cli.cfgmod.config_path", return_value="/etc/astrapi-admin/config.json"):
        rc = cli.cmd_pair(_pair_args())

    assert rc == 0
    mock_save.assert_called_once()


def test_cmd_apply_bricht_ohne_root_ab_vor_dem_config_laden():
    with patch("astrapi_admin_agent.cli.os.geteuid", return_value=1000), \
         patch("astrapi_admin_agent.cli.cfgmod.load") as mock_load:
        rc = cli.cmd_apply(SimpleNamespace())

    assert rc == 1
    mock_load.assert_not_called()
