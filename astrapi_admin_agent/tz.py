# astrapi_admin_agent/tz.py
"""Zeitzone + NTP-Sync ueber timedatectl setzen (T-321-ADMIN).

Globales Server-Setting (astrapi_admin.modules.hosts.agent_settings.
timezone()), kein Policy-Feld -- alle Hosts sollen dieselbe
Zeiteinteilung bekommen, siehe Nutzerentscheidung im Ticket. Das Feld
fehlt in der Policy-Antwort ganz, solange nichts konfiguriert ist --
cmd_apply() ruft ensure()/ensure_ntp() dann erst gar nicht auf.

Eine korrekt gesetzte Zeitzone allein macht die angezeigte Uhrzeit nur
dann richtig, wenn die absolute Systemzeit selbst stimmt -- deshalb
zusaetzlich ensure_ntp(), das NTP-Synchronisierung erzwingt (Nachtrag,
nachdem Hosts trotz "Status OK" falsch gehende Uhren zeigten: die
Zeitzone war korrekt gesetzt, aber die zugrunde liegende Zeit driftete
unbemerkt).

ensure()/ensure_ntp() geben (status, detail) zurueck -- status in
{'ok', 'changed', 'failed'}, wie files.enforce()/services.apply_state().
Ein 'failed' fliesst darueber in cli.py in den Report an den Server ein
(vorher wurden Fehler hier lautlos verschluckt und tauchten nie im
Gesamtstatus auf)."""
import subprocess


def current() -> str | None:
    """Best-effort: aktuell gesetzte Zeitzone, None wenn nicht ermittelbar
    (z.B. timedatectl fehlt) -- darf apply() nie zum Absturz bringen,
    analog zu pkg.reboot_required()."""
    try:
        r = subprocess.run(
            ["timedatectl", "show", "--property=Timezone", "--value"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return r.stdout.strip() or None
    except Exception:
        return None


def ensure(desired: str) -> tuple[str, str]:
    """Setzt die Zeitzone nur bei Abweichung vom Ist-Zustand (idempotent)
    -- ein unbedingter 'timedatectl set-timezone'-Aufruf bei jedem
    Poll-Zyklus waere zwar wirkungslos, wuerde aber unnoetig einen
    System-Log-Eintrag pro Zyklus erzeugen. Gibt (status, detail) zurueck,
    status in {'ok', 'changed', 'failed'}, wirft nie."""
    now = current()
    if now == desired:
        return "ok", f"bereits {desired}"
    try:
        subprocess.run(
            ["timedatectl", "set-timezone", desired],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return "changed", f"{now or 'unbekannt'} -> {desired}"
    except Exception as e:
        return "failed", f"Fehler: {e}"


def ntp_active() -> bool | None:
    """Best-effort: ist NTP-Synchronisierung aktuell aktiv (timedatectl-
    Feld 'NTP'), None wenn nicht ermittelbar -- analog current()."""
    try:
        r = subprocess.run(
            ["timedatectl", "show", "--property=NTP", "--value"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return r.stdout.strip() == "yes"
    except Exception:
        return None


def ensure_ntp() -> tuple[str, str]:
    """Aktiviert NTP-Synchronisierung nur bei Abweichung (idempotent) --
    ohne das bleibt eine korrekt gesetzte Zeitzone wirkungslos, sobald die
    absolute Systemzeit driftet. Gibt (status, detail) zurueck wie
    ensure(), wirft nie."""
    now = ntp_active()
    if now is True:
        return "ok", "NTP bereits aktiv"
    try:
        subprocess.run(
            ["timedatectl", "set-ntp", "true"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return "changed", f"NTP aktiviert (vorher: {'inaktiv' if now is False else 'unbekannt'})"
    except Exception as e:
        return "failed", f"Fehler: {e}"
