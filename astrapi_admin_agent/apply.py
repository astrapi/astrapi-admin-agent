# astrapi_admin_agent/apply.py
"""Wendet eine vom Server aufgeloeste Policy lokal an.

Bewusst KEINE Paketinstallation/-entfernung mehr (siehe E-004,
astrapi-hub-Vault): der Agent prueft nur noch, ob ein benoetigtes Paket
bereits installiert ist -- fehlt es, wird das als Fehler gemeldet statt
selbst zu installieren. Paketverwaltung (inkl. Paketquellen) bleibt
ausserhalb von astrapi-admin, manueller Schritt des Nutzers.

  1. Pakete-Check    (nur pruefen, nicht installieren)
  2. Config-Dateien enforce
  3. Services praesent (enabled_started/enabled/started)
  4. Nutzer enforce (E-012)
  5. Abwesenheit, separiert und zuletzt:
       Services disabled/disabled_stopped/stopped, Config-Dateien absent,
       Nutzer absent (nur was astrapi-admin selbst angelegt hat)

Jede Phase baut nicht auf einer vorherigen auf -- ein Fehlschlag in einer
Phase blockiert nicht die naechste, wird aber im Gesamtergebnis (ok=False)
sichtbar."""
from astrapi_admin_agent import files, pkg, services
from astrapi_admin_agent import state as statemod
from astrapi_admin_agent import users as usersmod


def _check_packages_required(names: list[str], backend: str, out: list[dict]) -> bool:
    all_ok = True
    for name in names:
        if not backend:
            out.append(
                {"name": name, "status": "failed", "detail": "kein unterstützter Paket-Manager gefunden"}
            )
            all_ok = False
        elif pkg.is_installed(name, backend):
            out.append({"name": name, "status": "ok"})
        else:
            out.append(
                {
                    "name": name,
                    "status": "failed",
                    "detail": f"Paket '{name}' ist nicht installiert -- wird nicht automatisch installiert",
                }
            )
            all_ok = False
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


def _apply_config_files_enforce(config_files: list[dict], out: list[dict], managed_paths: list[str]) -> bool:
    all_ok = True
    for cf in config_files:
        if cf.get("action") != "enforce":
            continue
        status, detail = files.enforce(cf)
        out.append({"path": cf["path"], "action": "enforce", "status": status, "detail": detail})
        if status == "changed" and cf["path"] not in managed_paths:
            managed_paths.append(cf["path"])
        if status == "failed":
            all_ok = False
    return all_ok


def _apply_users_enforce(user_entries: list[dict], out: list[dict], managed_users: list[str], backend: str) -> bool:
    all_ok = True
    for u in user_entries:
        if u.get("action") != "enforce":
            continue
        status, detail = usersmod.enforce(u, backend)
        out.append({"username": u["username"], "action": "enforce", "status": status, "detail": detail})
        if status == "changed" and u["username"] not in managed_users:
            managed_users.append(u["username"])
        if status == "failed":
            all_ok = False
    return all_ok


def _apply_users_absent(user_entries: list[dict], out: list[dict], managed_users: list[str]) -> bool:
    all_ok = True
    for u in user_entries:
        if u.get("action") != "absent":
            continue
        status, detail = usersmod.remove_if_managed(u["username"], managed_users)
        out.append({"username": u["username"], "action": "absent", "status": status, "detail": detail})
        if status == "changed" and u["username"] in managed_users:
            managed_users.remove(u["username"])
        if status == "failed":
            all_ok = False
    return all_ok


def apply_policy(policy: dict) -> dict:
    st = statemod.load()
    managed_paths = list(st.get("managed_paths", []))
    managed_users = list(st.get("managed_users", []))
    backend = pkg.detect_backend()

    packages_out: list[dict] = []
    services_out: list[dict] = []
    config_files_out: list[dict] = []
    users_out: list[dict] = []
    ok = True

    config_files = policy.get("config_files", [])
    user_entries = policy.get("users", [])

    # 1) Pakete-Check (nur pruefen)
    ok &= _check_packages_required(policy.get("packages_required", []), backend, packages_out)

    # 2) Config-Dateien enforce
    ok &= _apply_config_files_enforce(config_files, config_files_out, managed_paths)

    # 3) Services praesent
    ok &= _apply_services(policy.get("services", []), services.PRESENCE_STATES, services_out)

    # 4) Nutzer enforce (E-012)
    ok &= _apply_users_enforce(user_entries, users_out, managed_users, backend)

    # 5) Abwesenheit -- separiert, zuletzt
    ok &= _apply_services(policy.get("services", []), services.ABSENCE_STATES, services_out)
    for cf in config_files:
        if cf.get("action") != "absent":
            continue
        status, detail = files.remove_if_managed(cf["path"], managed_paths)
        config_files_out.append({"path": cf["path"], "action": "absent", "status": status, "detail": detail})
        if status == "changed" and cf["path"] in managed_paths:
            managed_paths.remove(cf["path"])
        if status == "failed":
            ok = False
    ok &= _apply_users_absent(user_entries, users_out, managed_users)

    st["managed_paths"] = managed_paths
    st["managed_users"] = managed_users
    statemod.save(st)

    return {
        "ok": ok,
        "packages": packages_out,
        "services": services_out,
        "config_files": config_files_out,
        "users": users_out,
    }


def summarize(policy: dict, result: dict) -> tuple[str, str]:
    """Leitet den an /api/agent/report zu meldenden status + eine kurze
    Zusammenfassung aus dem apply()-Ergebnis ab. policy_conflict (Server-
    seitig, siehe policies.engine.resolve_policy_for_host) wiegt schwerer
    als ein lokaler skipped_conflict (Fremdbesitz), beide schwerer als
    reine Aenderungen."""
    items = result["packages"] + result["services"] + result["config_files"] + result["users"]
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
