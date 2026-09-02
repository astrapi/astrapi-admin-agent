"""users.py -- E-012: idempotente Nutzerkonten-Durchsetzung (useradd/
usermod/gpasswd gemockt, SSH-Key-Schreiben real gegen tmp_path via
files.atomic_write) sowie die zentrale Sicherheitsregel: nur ein von
diesem Agenten selbst angelegter Account (managed_users) darf per
action=absent wieder per 'userdel -r' gelöscht werden."""
from unittest.mock import patch

from astrapi_admin_agent import users


class _FakePw:
    def __init__(self, name, uid=1500, shell="/bin/bash", home="/home/x", gid=1500):
        self.pw_name = name
        self.pw_uid = uid
        self.pw_shell = shell
        self.pw_dir = home
        self.pw_gid = gid


def _fake_run(returncode=0, stdout="", stderr=""):
    class _Result:
        pass

    r = _Result()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


# ── user_exists() ───────────────────────────────────────────────────────


def test_user_exists_true():
    with patch("astrapi_admin_agent.users.pwd.getpwnam", return_value=_FakePw("alice")):
        assert users.user_exists("alice") is True


def test_user_exists_false():
    with patch("astrapi_admin_agent.users.pwd.getpwnam", side_effect=KeyError):
        assert users.user_exists("ghost") is False


# ── enforce() ────────────────────────────────────────────────────────────


def _enforce_env(tmp_path, exists=True, shell="/bin/bash", sudo_member=False):
    home = tmp_path / "home"
    home.mkdir()
    pw = _FakePw("alice", shell=shell, home=str(home))
    patches = [
        patch("astrapi_admin_agent.users.user_exists", return_value=exists),
        patch("astrapi_admin_agent.users.pwd.getpwnam", return_value=pw),
        patch("astrapi_admin_agent.users._is_group_member", return_value=sudo_member),
        patch("astrapi_admin_agent.users._primary_group", return_value="alice"),
        patch("astrapi_admin_agent.users.shutil.chown"),
    ]
    return patches, home


def test_enforce_legt_neuen_nutzer_an(tmp_path):
    patches, _home = _enforce_env(tmp_path, exists=False)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patch("astrapi_admin_agent.users.subprocess.run", return_value=_fake_run(0)) as mock_run:
        status, detail = users.enforce({"username": "alice", "action": "enforce"}, "apt")

    assert status == "changed"
    assert "angelegt" in detail
    assert mock_run.call_args_list[0].args[0][:2] == ["useradd", "-m"]


def test_enforce_aktualisiert_abweichende_shell(tmp_path):
    patches, _home = _enforce_env(tmp_path, exists=True, shell="/bin/sh")
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patch("astrapi_admin_agent.users.subprocess.run", return_value=_fake_run(0)) as mock_run:
        status, detail = users.enforce({"username": "alice", "action": "enforce", "shell": "/bin/bash"}, "apt")

    assert status == "changed"
    assert "Shell" in detail
    assert mock_run.call_args_list[0].args[0] == ["usermod", "-s", "/bin/bash", "alice"]


def test_enforce_fuegt_zur_sudo_gruppe_hinzu(tmp_path):
    patches, _home = _enforce_env(tmp_path, exists=True, sudo_member=False)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patch("astrapi_admin_agent.users.subprocess.run", return_value=_fake_run(0)) as mock_run:
        status, detail = users.enforce({"username": "alice", "action": "enforce", "sudo": True}, "apt")

    assert status == "changed"
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert ["usermod", "-aG", "sudo", "alice"] in calls


def test_enforce_entfernt_aus_sudo_gruppe(tmp_path):
    patches, _home = _enforce_env(tmp_path, exists=True, sudo_member=True)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patch("astrapi_admin_agent.users.subprocess.run", return_value=_fake_run(0)) as mock_run:
        status, detail = users.enforce({"username": "alice", "action": "enforce", "sudo": False}, "apt")

    assert status == "changed"
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert ["gpasswd", "-d", "alice", "sudo"] in calls


def test_enforce_pacman_backend_nutzt_wheel_gruppe(tmp_path):
    patches, _home = _enforce_env(tmp_path, exists=True, sudo_member=False)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patch("astrapi_admin_agent.users.subprocess.run", return_value=_fake_run(0)) as mock_run:
        users.enforce({"username": "alice", "action": "enforce", "sudo": True}, "pacman")

    calls = [c.args[0] for c in mock_run.call_args_list]
    assert ["usermod", "-aG", "wheel", "alice"] in calls


def test_enforce_schreibt_ssh_keys(tmp_path):
    patches, home = _enforce_env(tmp_path, exists=True)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patch("astrapi_admin_agent.users.subprocess.run", return_value=_fake_run(0)):
        status, detail = users.enforce(
            {"username": "alice", "action": "enforce", "ssh_keys": ["ssh-ed25519 AAAA... a@b"]}, "apt"
        )

    assert status == "changed"
    keys_path = home / ".ssh" / "authorized_keys"
    assert keys_path.read_text() == "ssh-ed25519 AAAA... a@b\n"
    assert oct(keys_path.stat().st_mode & 0o777) == "0o600"


def test_enforce_ist_no_op_ohne_aenderung(tmp_path):
    patches, home = _enforce_env(tmp_path, exists=True)
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(mode=0o700)
    (ssh_dir / "authorized_keys").write_text("ssh-ed25519 AAAA... a@b\n")

    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patch("astrapi_admin_agent.users.subprocess.run", return_value=_fake_run(0)) as mock_run:
        status, detail = users.enforce(
            {"username": "alice", "action": "enforce", "ssh_keys": ["ssh-ed25519 AAAA... a@b"]}, "apt"
        )

    assert status == "ok"
    assert detail == "bereits im Zielzustand"
    mock_run.assert_not_called()


def test_enforce_meldet_failed_bei_useradd_fehler(tmp_path):
    patches, _home = _enforce_env(tmp_path, exists=False)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patch("astrapi_admin_agent.users.subprocess.run", return_value=_fake_run(1, stderr="boom")):
        status, detail = users.enforce({"username": "alice", "action": "enforce"}, "apt")

    assert status == "failed"
    assert "boom" in detail


# ── remove_if_managed() ────────────────────────────────────────────────


def test_remove_if_managed_loescht_fremden_account_nicht():
    with patch("astrapi_admin_agent.users.user_exists", return_value=True), \
         patch("astrapi_admin_agent.users.subprocess.run") as mock_run:
        status, detail = users.remove_if_managed("alice", managed_users=[])

    assert status == "skipped_conflict"
    mock_run.assert_not_called()


def test_remove_if_managed_loescht_selbst_angelegten_account():
    with patch("astrapi_admin_agent.users.user_exists", return_value=True), \
         patch("astrapi_admin_agent.users.subprocess.run", return_value=_fake_run(0)) as mock_run:
        status, detail = users.remove_if_managed("alice", managed_users=["alice"])

    assert status == "changed"
    assert mock_run.call_args[0][0] == ["userdel", "-r", "alice"]


def test_remove_if_managed_ist_ok_wenn_bereits_weg():
    with patch("astrapi_admin_agent.users.user_exists", return_value=False), \
         patch("astrapi_admin_agent.users.subprocess.run") as mock_run:
        status, detail = users.remove_if_managed("alice", managed_users=["alice"])

    assert status == "ok"
    mock_run.assert_not_called()


def test_remove_if_managed_meldet_failed_bei_userdel_fehler():
    with patch("astrapi_admin_agent.users.user_exists", return_value=True), \
         patch("astrapi_admin_agent.users.subprocess.run", return_value=_fake_run(1, stderr="busy")):
        status, detail = users.remove_if_managed("alice", managed_users=["alice"])

    assert status == "failed"
    assert "busy" in detail


# ── inventory() ──────────────────────────────────────────────────────────


def test_inventory_filtert_system_accounts_unter_uid_min(tmp_path):
    home = tmp_path / "alice"
    home.mkdir()
    entries = [_FakePw("root", uid=0, home=str(tmp_path)), _FakePw("alice", uid=1500, home=str(home))]
    with patch("astrapi_admin_agent.users.pwd.getpwall", return_value=entries), \
         patch("astrapi_admin_agent.users.grp.getgrall", return_value=[]), \
         patch("astrapi_admin_agent.users.state.load", return_value={"managed_users": []}):
        result = users.inventory()

    assert [u["username"] for u in result] == ["alice"]


def test_inventory_erkennt_sudo_mitgliedschaft(tmp_path):
    home = tmp_path / "alice"
    home.mkdir()
    entries = [_FakePw("alice", uid=1500, home=str(home))]

    class _G:
        gr_name = "sudo"
        gr_mem = ["alice"]

    with patch("astrapi_admin_agent.users.pwd.getpwall", return_value=entries), \
         patch("astrapi_admin_agent.users.grp.getgrall", return_value=[_G()]), \
         patch("astrapi_admin_agent.users.state.load", return_value={"managed_users": []}):
        result = users.inventory()

    assert result[0]["sudo"] is True


def test_inventory_erkennt_verwaltete_accounts(tmp_path):
    home = tmp_path / "alice"
    home.mkdir()
    entries = [_FakePw("alice", uid=1500, home=str(home))]
    with patch("astrapi_admin_agent.users.pwd.getpwall", return_value=entries), \
         patch("astrapi_admin_agent.users.grp.getgrall", return_value=[]), \
         patch("astrapi_admin_agent.users.state.load", return_value={"managed_users": ["alice"]}):
        result = users.inventory()

    assert result[0]["managed"] is True


def test_inventory_erkennt_vorhandene_ssh_keys(tmp_path):
    home = tmp_path / "alice"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "authorized_keys").write_text("ssh-ed25519 x\n")
    entries = [_FakePw("alice", uid=1500, home=str(home))]
    with patch("astrapi_admin_agent.users.pwd.getpwall", return_value=entries), \
         patch("astrapi_admin_agent.users.grp.getgrall", return_value=[]), \
         patch("astrapi_admin_agent.users.state.load", return_value={"managed_users": []}):
        result = users.inventory()

    assert result[0]["has_ssh_keys"] is True
