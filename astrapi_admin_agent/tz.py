# astrapi_admin_agent/tz.py
"""Zeitzone ueber timedatectl setzen (T-321-ADMIN).

Globales Server-Setting (astrapi_admin.modules.hosts.agent_settings.
timezone()), kein Policy-Feld -- alle Hosts sollen dieselbe
Zeiteinteilung bekommen, siehe Nutzerentscheidung im Ticket. Das Feld
fehlt in der Policy-Antwort ganz, solange nichts konfiguriert ist --
cmd_apply() ruft ensure() dann erst gar nicht auf.
"""
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


def ensure(desired: str) -> tuple[bool, str]:
    """Setzt die Zeitzone nur bei Abweichung vom Ist-Zustand (idempotent)
    -- ein unbedingter 'timedatectl set-timezone'-Aufruf bei jedem
    Poll-Zyklus waere zwar wirkungslos, wuerde aber unnoetig einen
    System-Log-Eintrag pro Zyklus erzeugen. Gibt (geaendert, Detailtext)
    zurueck, wirft nie -- best-effort wie reboot_required()/inventory()
    in cli.py."""
    now = current()
    if now == desired:
        return False, f"bereits {desired}"
    try:
        subprocess.run(
            ["timedatectl", "set-timezone", desired],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return True, f"{now or 'unbekannt'} -> {desired}"
    except Exception as e:
        return False, f"Fehler: {e}"
