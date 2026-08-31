"""apply.py: Orchestrierung der vier Phasen -- insbesondere dass Abwesenheit
(Services/Config-Dateien absent) immer zuletzt und unabhaengig von der
Praesenz-Phase laeuft, ein Fehlschlag eine Phase nicht blockiert, und
summarize() die richtige Statuspriorität ableitet. Pakete werden seit E-004
nur noch auf Anwesenheit GEPRUEFT, nie installiert/entfernt."""
from astrapi_admin_agent import apply as applymod


def _policy(**overrides):
    base = {
        "packages_required": [],
        "services": [],
        "config_files": [],
        "conflicts": [],
    }
    base.update(overrides)
    return base


def _patched_state(monkeypatch, managed_paths=None):
    state = {"managed_paths": list(managed_paths or []), "policy_hash": ""}
    monkeypatch.setattr(applymod.statemod, "load", lambda: state)
    saved = {}
    monkeypatch.setattr(applymod.statemod, "save", lambda s: saved.update(s))
    return state, saved


def test_apply_policy_meldet_vorhandene_pakete_als_ok(monkeypatch):
    _patched_state(monkeypatch)
    monkeypatch.setattr(applymod.pkg, "detect_backend", lambda: "pacman")
    monkeypatch.setattr(applymod.pkg, "is_installed", lambda name, backend: name == "vim")

    result = applymod.apply_policy(_policy(packages_required=["vim", "htop"]))

    statuses = {p["name"]: p["status"] for p in result["packages"]}
    assert statuses == {"vim": "ok", "htop": "failed"}
    assert result["ok"] is False


def test_apply_policy_fehlendes_paket_wird_nicht_installiert(monkeypatch):
    """Kernverhalten seit E-004: kein pkg.install()-Aufruf mehr -- ein
    fehlendes Paket ist ein reiner Fehlerfall, keine Aktion."""
    _patched_state(monkeypatch)
    monkeypatch.setattr(applymod.pkg, "detect_backend", lambda: "apt")
    monkeypatch.setattr(applymod.pkg, "is_installed", lambda name, backend: False)
    assert not hasattr(applymod.pkg, "install")

    result = applymod.apply_policy(_policy(packages_required=["caddy"]))

    assert result["packages"] == [
        {
            "name": "caddy",
            "status": "failed",
            "detail": "Paket 'caddy' ist nicht installiert -- wird nicht automatisch installiert",
        }
    ]


def test_apply_policy_config_dateien_laufen_vor_services(monkeypatch):
    _patched_state(monkeypatch)
    call_order = []
    monkeypatch.setattr(applymod.pkg, "detect_backend", lambda: "")
    monkeypatch.setattr(applymod.files, "enforce", lambda cf: (call_order.append("config"), ("changed", "geschrieben"))[1])
    monkeypatch.setattr(
        applymod.services,
        "apply_state",
        lambda name, state: (call_order.append(f"service_{state}"), (True, "ok"))[1],
    )

    applymod.apply_policy(
        _policy(
            config_files=[{"path": "/etc/caddy/Caddyfile", "action": "enforce"}],
            services=[{"name": "caddy", "state": "enabled_started"}],
        )
    )

    assert call_order == ["config", "service_enabled_started"]


def test_apply_policy_abwesenheit_laeuft_nach_praesenz(monkeypatch):
    _patched_state(monkeypatch)
    call_order = []
    monkeypatch.setattr(applymod.pkg, "detect_backend", lambda: "")
    monkeypatch.setattr(
        applymod.services,
        "apply_state",
        lambda name, state: (call_order.append(f"service_{state}"), (True, "ok"))[1],
    )

    applymod.apply_policy(
        _policy(
            services=[{"name": "nginx", "state": "enabled_started"}, {"name": "telnetd", "state": "disabled_stopped"}],
        )
    )

    assert call_order.index("service_enabled_started") < call_order.index("service_disabled_stopped")


def test_apply_policy_ohne_backend_meldet_alle_pakete_failed(monkeypatch):
    _patched_state(monkeypatch)
    monkeypatch.setattr(applymod.pkg, "detect_backend", lambda: "")

    result = applymod.apply_policy(_policy(packages_required=["htop"]))

    assert result["ok"] is False
    assert result["packages"][0]["status"] == "failed"


def test_apply_policy_config_datei_wird_zu_managed_paths_hinzugefuegt(monkeypatch):
    _, saved = _patched_state(monkeypatch)
    monkeypatch.setattr(applymod.pkg, "detect_backend", lambda: "")
    monkeypatch.setattr(applymod.files, "enforce", lambda cf: ("changed", "geschrieben"))

    applymod.apply_policy(_policy(config_files=[{"path": "/etc/foo.conf", "action": "enforce"}]))

    assert "/etc/foo.conf" in saved["managed_paths"]


def test_apply_policy_config_absent_entfernt_aus_managed_paths(monkeypatch):
    _, saved = _patched_state(monkeypatch, managed_paths=["/etc/foo.conf"])
    monkeypatch.setattr(applymod.pkg, "detect_backend", lambda: "")
    monkeypatch.setattr(applymod.files, "remove_if_managed", lambda path, managed: ("changed", "entfernt"))

    applymod.apply_policy(_policy(config_files=[{"path": "/etc/foo.conf", "action": "absent"}]))

    assert "/etc/foo.conf" not in saved["managed_paths"]


def test_apply_policy_ein_fehlschlag_blockiert_nicht_die_naechste_phase(monkeypatch):
    _patched_state(monkeypatch)
    monkeypatch.setattr(applymod.pkg, "detect_backend", lambda: "pacman")
    monkeypatch.setattr(applymod.pkg, "is_installed", lambda name, backend: False)
    monkeypatch.setattr(applymod.files, "enforce", lambda cf: ("changed", "geschrieben"))

    result = applymod.apply_policy(_policy(
        packages_required=["htop"],
        config_files=[{"path": "/etc/foo.conf", "action": "enforce"}],
    ))

    assert result["ok"] is False
    assert result["config_files"][0]["status"] == "changed"


def test_summarize_status_prioritaet_failed_schlaegt_alles():
    policy = _policy(conflicts=[{"type": "package", "name": "x"}])
    result = {
        "packages": [{"status": "failed"}],
        "services": [{"status": "skipped_conflict"}],
        "config_files": [],
    }
    status, summary = applymod.summarize(policy, result)
    assert status == "error"
    assert "fehlgeschlagen" in summary


def test_summarize_status_conflict_vor_drift():
    policy = _policy(conflicts=[{"type": "package", "name": "x"}])
    result = {"packages": [{"status": "skipped_conflict"}], "services": [], "config_files": []}
    status, _ = applymod.summarize(policy, result)
    assert status == "conflict"


def test_summarize_status_drift_bei_skipped_ohne_policy_konflikt():
    policy = _policy()
    result = {"packages": [{"status": "skipped_conflict"}], "services": [], "config_files": []}
    status, _ = applymod.summarize(policy, result)
    assert status == "drift"


def test_summarize_status_ok_ohne_aenderungen():
    policy = _policy()
    result = {"packages": [{"status": "ok"}], "services": [], "config_files": []}
    status, summary = applymod.summarize(policy, result)
    assert status == "ok"
    assert summary == "keine Änderungen nötig"
