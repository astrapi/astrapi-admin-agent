"""Regressionsschutz für die beiden Sicherheitsregeln in files.py:
fremd besessene Pfade werden nie überschrieben, und action=absent löscht
nur, was der Agent selbst angelegt hat (managed_paths)."""
import grp
import os
import pwd
from unittest.mock import patch

from astrapi_admin_agent import files

_OWNER = pwd.getpwuid(os.getuid()).pw_name
_GROUP = grp.getgrgid(os.getgid()).gr_name


def _cf(path, content="hallo\n", mode="0644"):
    return {"path": str(path), "content": content, "mode": mode, "owner": _OWNER, "group": _GROUP}


def test_enforce_ueberschreibt_fremdbesessenen_pfad_nicht(tmp_path):
    path = tmp_path / "vimrc"
    path.write_text("original\n")

    with patch("astrapi_admin_agent.files.is_package_owned", return_value=True):
        status, detail = files.enforce(_cf(path, content="neu\n"))

    assert status == "skipped_conflict"
    assert path.read_text() == "original\n"


def test_enforce_mit_force_ueberschreibt_fremdbesessenen_pfad(tmp_path):
    """Expliziter Opt-out pro Datei (force: true) -- z.B. ein Template wie
    "Caddy", das bewusst die vom Paket mitgelieferte Platzhalter-Caddyfile
    ersetzen soll. Bleibt ein bewusster Ausnahmefall, kein Abschaffen der
    Schutzregel selbst (siehe die Tests ohne force oben/unten)."""
    path = tmp_path / "Caddyfile"
    path.write_text("platzhalter\n")
    cf = _cf(path, content="eigene-config\n")
    cf["force"] = True

    with patch("astrapi_admin_agent.files.is_package_owned", return_value=True):
        status, detail = files.enforce(cf)

    assert status == "changed"
    assert path.read_text() == "eigene-config\n"


def test_enforce_schreibt_neue_datei(tmp_path):
    path = tmp_path / "sub" / "config.conf"

    with patch("astrapi_admin_agent.files.is_package_owned", return_value=False):
        status, detail = files.enforce(_cf(path, content="inhalt\n"))

    assert status == "changed"
    assert path.read_text() == "inhalt\n"
    assert oct(path.stat().st_mode & 0o777) == "0o644"


def test_enforce_ist_no_op_bei_unveraenderter_datei(tmp_path):
    path = tmp_path / "config.conf"
    cf = _cf(path, content="inhalt\n")

    with patch("astrapi_admin_agent.files.is_package_owned", return_value=False):
        first = files.enforce(cf)
        assert first[0] == "changed"
        second_status, second_detail = files.enforce(cf)

    assert second_status == "ok"
    assert second_detail == "unverändert"


def test_enforce_meldet_failed_bei_schreibfehler(tmp_path):
    path = tmp_path / "config.conf"

    with patch("astrapi_admin_agent.files.is_package_owned", return_value=False), \
         patch("astrapi_admin_agent.files.atomic_write", side_effect=OSError("Festplatte voll")):
        status, detail = files.enforce(_cf(path))

    assert status == "failed"
    assert "voll" in detail


def test_remove_if_managed_loescht_fremde_datei_nicht(tmp_path):
    path = tmp_path / "fremd.conf"
    path.write_text("fremd\n")

    status, detail = files.remove_if_managed(str(path), managed_paths=[])

    assert status == "skipped_conflict"
    assert path.exists()


def test_remove_if_managed_loescht_selbst_angelegte_datei(tmp_path):
    path = tmp_path / "eigene.conf"
    path.write_text("eigen\n")

    status, detail = files.remove_if_managed(str(path), managed_paths=[str(path)])

    assert status == "changed"
    assert not path.exists()


def test_remove_if_managed_ist_ok_wenn_bereits_weg(tmp_path):
    path = tmp_path / "schon-weg.conf"

    status, detail = files.remove_if_managed(str(path), managed_paths=[str(path)])

    assert status == "ok"
    assert detail == "bereits entfernt"
