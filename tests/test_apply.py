"""apply.py: Orchestrierung der vier Phasen -- insbesondere dass Abwesenheit
(Pakete/Services/Config-Dateien absent) immer zuletzt und unabhaengig von
der Praesenz-Phase laeuft, ein Fehlschlag eine Phase nicht blockiert, und
summarize() die richtige Statuspriorität ableitet."""
from astrapi_admin_agent import apply as applymod


def _policy(**overrides):
    base = {
        "packages_present": [],
        "packages_absent": [],
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


def test_apply_policy_installiert_nur_fehlende_pakete(monkeypatch):
    _patched_state(monkeypatch)
    monkeypatch.setattr(applymod.pkg, "detect_backend", lambda: "pacman")
    monkeypatch.setattr(applymod.pkg, "is_installed", lambda name, backend: name == "vim")
    installed = {}
    monkeypatch.setattr(applymod.pkg, "install", lambda names, backend: (installed.setdefault("names", names), (True, ""))[1])

    result = applymod.apply_policy(_policy(packages_present=["vim", "htop"]))

    assert installed["names"] == ["htop"]
    statuses = {p["name"]: p["status"] for p in result["packages"]}
    assert statuses == {"vim": "ok", "htop": "changed"}


def test_apply_policy_abwesenheit_laeuft_nach_praesenz(monkeypatch):
    """Dasselbe Paket taucht (theoretisch) nicht gleichzeitig in present und
    absent auf, aber die Reihenfolge selbst muss stimmen: absent-Pakete
    duerfen nicht vor der services-Praesenz-Phase drankommen."""
    _patched_state(monkeypatch)
    call_order = []
    monkeypatch.setattr(applymod.pkg, "detect_backend", lambda: "pacman")
    # htop fehlt noch (-> present-Phase installiert), telnet ist noch da (-> absent-Phase entfernt)
    monkeypatch.setattr(applymod.pkg, "is_installed", lambda name, backend: name == "telnet")
    monkeypatch.setattr(applymod.pkg, "install", lambda names, backend: (call_order.append("packages_present"), (True, ""))[1])
    monkeypatch.setattr(applymod.pkg, "remove_one", lambda name, backend: (call_order.append("packages_absent"), (True, ""))[1])
    monkeypatch.setattr(applymod.services, "apply_state", lambda name, state: (call_order.append(f"service_{state}"), (True, "ok"))[1])

    applymod.apply_policy(_policy(
        packages_present=["htop"],
        packages_absent=["telnet"],
        services=[{"name": "nginx", "state": "enabled_started"}, {"name": "telnetd", "state": "disabled_stopped"}],
    ))

    assert call_order.index("packages_present") < call_order.index("packages_absent")
    assert call_order.index("service_enabled_started") < call_order.index("service_disabled_stopped")
    assert call_order.index("packages_present") < call_order.index("service_disabled_stopped")


def test_apply_policy_ohne_backend_meldet_alle_pakete_failed(monkeypatch):
    _patched_state(monkeypatch)
    monkeypatch.setattr(applymod.pkg, "detect_backend", lambda: "")

    result = applymod.apply_policy(_policy(packages_present=["htop"]))

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


def test_apply_policy_before_packages_config_datei_laeuft_vor_dem_paket_install(monkeypatch):
    """Am echten LXC entdeckt: eine Paketquelle (config_files-Eintrag) muss
    VOR dem Paket-Install stehen, sonst kennt der Paketmanager die Quelle
    noch nicht, wenn er das Paket sucht."""
    _patched_state(monkeypatch)
    call_order = []
    monkeypatch.setattr(applymod.pkg, "detect_backend", lambda: "apt")
    monkeypatch.setattr(applymod.pkg, "is_installed", lambda name, backend: False)
    monkeypatch.setattr(
        applymod.pkg,
        "install",
        lambda names, backend: (call_order.append("packages_present"), (True, ""))[1],
    )

    def _fake_enforce(cf):
        call_order.append(f"config_{cf['path']}")
        return "changed", "geschrieben"

    monkeypatch.setattr(applymod.files, "enforce", _fake_enforce)

    applymod.apply_policy(
        _policy(
            packages_present=["caddy"],
            config_files=[
                {"path": "/etc/apt/sources.list.d/caddy.sources", "action": "enforce", "before_packages": True},
                {"path": "/etc/caddy/Caddyfile", "action": "enforce"},
            ],
        )
    )

    assert call_order == [
        "config_/etc/apt/sources.list.d/caddy.sources",
        "packages_present",
        "config_/etc/caddy/Caddyfile",
    ]


def test_apply_policy_ein_fehlschlag_blockiert_nicht_die_naechste_phase(monkeypatch):
    _patched_state(monkeypatch)
    monkeypatch.setattr(applymod.pkg, "detect_backend", lambda: "pacman")
    monkeypatch.setattr(applymod.pkg, "is_installed", lambda name, backend: False)
    monkeypatch.setattr(applymod.pkg, "install", lambda names, backend: (False, "Netzwerkfehler"))
    monkeypatch.setattr(applymod.files, "enforce", lambda cf: ("changed", "geschrieben"))

    result = applymod.apply_policy(_policy(
        packages_present=["htop"],
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
