from unittest.mock import patch

from astrapi_admin_agent.osinfo import detect_os_type


def _with_os_release(text):
    return patch("astrapi_admin_agent.osinfo.Path.read_text", return_value=text)


def test_erkennt_archlinux():
    with _with_os_release('ID=arch\nNAME="Arch Linux"\n'):
        assert detect_os_type() == "archlinux"


def test_erkennt_debian():
    with _with_os_release('ID=debian\nNAME="Debian GNU/Linux"\n'):
        assert detect_os_type() == "debian"


def test_erkennt_debian_derivat_ueber_id_like():
    with _with_os_release('ID=ubuntu\nID_LIKE=debian\n'):
        assert detect_os_type() == "debian"


def test_unbekannte_distro_liefert_rohe_id():
    with _with_os_release('ID=fedora\n'):
        assert detect_os_type() == "fedora"


def test_fehlende_datei_liefert_leeren_string():
    with patch("astrapi_admin_agent.osinfo.Path.read_text", side_effect=OSError):
        assert detect_os_type() == ""
