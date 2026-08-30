# astrapi_admin_agent/apply.py
"""Wendet eine vom Server aufgeloeste Policy lokal an -- in aufsteigendem
Risiko, wie im Rollout-Plan festgelegt:

  1. Pakete praesent      (risikoarm, gebuendelter Installationsaufruf)
  2. Services praesent    (enabled_started/enabled/started)
  3. Config-Dateien enforce
  4. Abwesenheit, separiert und zuletzt:
       Pakete absent, Services disabled/disabled_stopped/stopped,
       Config-Dateien absent

Jede Phase baut nicht auf einer vorherigen auf -- ein Fehlschlag in einer
Phase blockiert nicht die naechste, wird aber im Gesamtergebnis (ok=False)
sichtbar."""
from astrapi_admin_agent import files, pkg, services
from astrapi_admin_agent import state as statemod


def _apply_packages_present(names: list[str], backend: str, out: list[dict]) -> bool:
    if not backend:
        for name in names:
            out.append(
                {
                    "name": name,
                    "action": "present",
                    "status": "failed",
                    "detail": "kein unterstützter Paket-Manager gefunden",
                }
            )
        return not names

    missing = [n for n in names if not pkg.is_installed(n, backend)]
    for name in names:
        if name not in missing:
            out.append({"name": name, "action": "present", "status": "ok"})

    if not missing:
        return True

    ok, output = pkg.install(missing, backend)
    status = "changed" if ok else "failed"
    for name in missing:
        out.append({"name": name, "action": "present", "status": status, "detail": "" if ok else output})
    return ok


def _apply_packages_absent(names: list[str], backend: str, out: list[dict]) -> bool:
    all_ok = True
    for name in names:
        if not backend or not pkg.is_installed(name, backend):
            out.append({"name": name, "action": "absent", "status": "ok"})
            continue
        ok, output = pkg.remove_one(name, backend)
        out.append(
            {"name": name, "action": "absent", "status": "changed" if ok else "failed", "detail": "" if ok else output}
        )
        all_ok = all_ok and ok
    return all_ok


def _apply_services(svcs: list[dict], state_filter: set, out: list[dict]) -> bool:
    all_ok = True
    for svc in svcs:
        if svc.get("state") not in state_filter:
            continue
        ok, detail = services.apply_state(svc["name"], svc["state"])
        status = "ok" if (ok and detail == "bereits im Zielzustand") else ("changed" if ok else "failed")
        out.append({"name": svc["name"], "target_state": svc["state"], "status": status, "detail": detail})
        all_ok = all_ok and ok
    return all_ok


def apply_policy(policy: dict) -> dict:
    st = statemod.load()
    managed_paths = list(st.get("managed_paths", []))
    backend = pkg.detect_backend()

    packages_out: list[dict] = []
    services_out: list[dict] = []
    config_files_out: list[dict] = []
    ok = True

    # 1) Pakete praesent
    ok &= _apply_packages_present(policy.get("packages_present", []), backend, packages_out)

    # 2) Services praesent
    ok &= _apply_services(policy.get("services", []), services.PRESENCE_STATES, services_out)

    # 3) Config-Dateien enforce
    for cf in policy.get("config_files", []):
        if cf.get("action") != "enforce":
            continue
        status, detail = files.enforce(cf)
        config_files_out.append({"path": cf["path"], "action": "enforce", "status": status, "detail": detail})
        if status == "changed" and cf["path"] not in managed_paths:
            managed_paths.append(cf["path"])
        if status == "failed":
            ok = False

    # 4) Abwesenheit -- separiert, zuletzt
    ok &= _apply_packages_absent(policy.get("packages_absent", []), backend, packages_out)
    ok &= _apply_services(policy.get("services", []), services.ABSENCE_STATES, services_out)
    for cf in policy.get("config_files", []):
        if cf.get("action") != "absent":
            continue
        status, detail = files.remove_if_managed(cf["path"], managed_paths)
        config_files_out.append({"path": cf["path"], "action": "absent", "status": status, "detail": detail})
        if status == "changed" and cf["path"] in managed_paths:
            managed_paths.remove(cf["path"])
        if status == "failed":
            ok = False

    st["managed_paths"] = managed_paths
    statemod.save(st)

    return {"ok": ok, "packages": packages_out, "services": services_out, "config_files": config_files_out}


def summarize(policy: dict, result: dict) -> tuple[str, str]:
    """Leitet den an /api/agent/report zu meldenden status + eine kurze
    Zusammenfassung aus dem apply()-Ergebnis ab. policy_conflict (Server-
    seitig, siehe policies.engine.resolve_policy_for_host) wiegt schwerer
    als ein lokaler skipped_conflict (Fremdbesitz), beide schwerer als
    reine Aenderungen."""
    items = result["packages"] + result["services"] + result["config_files"]
    n_changed = sum(1 for i in items if i["status"] == "changed")
    n_failed = sum(1 for i in items if i["status"] == "failed")
    n_skipped = sum(1 for i in items if i["status"] == "skipped_conflict")
    n_policy_conflicts = len(policy.get("conflicts", []))

    parts = []
    if n_changed:
        parts.append(f"{n_changed} geändert")
    if n_failed:
        parts.append(f"{n_failed} fehlgeschlagen")
    if n_skipped:
        parts.append(f"{n_skipped} übersprungen (Fremdbesitz)")
    if n_policy_conflicts:
        parts.append(f"{n_policy_conflicts} Policy-Konflikt(e)")
    summary = ", ".join(parts) or "keine Änderungen nötig"

    if n_failed:
        status = "error"
    elif n_policy_conflicts:
        status = "conflict"
    elif n_skipped:
        status = "drift"
    else:
        status = "ok"
    return status, summary
