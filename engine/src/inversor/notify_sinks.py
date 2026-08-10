"""
Renderizadores de salida. CERO red.

Este módulo devuelve payloads; no los manda. Es deliberado: en cuanto una
función hace `POST` deja de poder probarse sin red, y CLAUDE.md prohíbe tests
que peguen a una API. Quien quiera entregar el aviso hace el `curl` con lo que
devuelve `render_ntfy` — el transporte es responsabilidad del CI, no del motor.

ntfy.sh se elige porque no requiere cuenta, ni llaves, ni backend: publicar en
un topic es un POST a una URL. Coherente con un repo que no guarda secretos
(regla 2). El topic ES el secreto; trátalo como tal.
"""
from __future__ import annotations

from typing import Any

from .notify import Notification

# Topic por defecto. Es un placeholder: un topic de ntfy es público para quien
# lo adivine, así que en producción se pasa por parámetro desde una variable de
# entorno del CI, nunca se commitea el real.
NTFY_TOPIC_DEFAULT = "inversor-min-cambios"

# ntfy: max, high, default, low, min.
NTFY_PRIORITY: dict[str, str] = {"HIGH": "high", "MEDIUM": "default", "INFO": "low"}

# Nombres de tag de ntfy (no son emojis literales: el cliente los traduce).
NTFY_TAGS: dict[str, tuple[str, ...]] = {
    "ACTION_CHANGED": ("rotating_light", "money_with_wings"),
    "BLOCKER_RAISED": ("no_entry",),
    "BLOCKER_CLEARED": ("white_check_mark",),
    "REGIME_FLIPPED": ("chart_with_upwards_trend",),
    "HURDLE_MOVED": ("bar_chart",),
    "MATERIALITY_FLIPPED": ("mag",),
    "FEE_BUDGET_LOW": ("warning",),
    "OVERTRADING_DETECTED": ("stop_sign",),
    "FLAPPING_DETECTED": ("repeat",),
}

PRIORIDAD_ES: dict[str, str] = {"HIGH": "ALTA", "MEDIUM": "MEDIA", "INFO": "INFO"}


def render_ntfy(n: Notification, topic: str = NTFY_TOPIC_DEFAULT) -> dict[str, Any]:
    """
    Payload para `POST https://ntfy.sh/<topic>`: headers + body. No manda nada.

    El cuerpo lleva SIEMPRE el razonamiento y la estrategia completos. Una
    notificación que sólo dice "cambió la acción" obliga a abrir la app para
    saber qué hacer, y a las 11 de la noche eso se traduce en operar sin leer.
    """
    cuerpo: list[str] = [n.body, ""]
    cuerpo.append("**Por qué**")
    cuerpo += [f"- {r}" for r in n.razonamiento]
    cuerpo.append("")
    cuerpo.append("**Qué hacer**")
    cuerpo += [f"- {e}" for e in n.estrategia]
    cuerpo.append("")
    cuerpo.append(f"_{n.trigger} · prioridad {PRIORIDAD_ES[n.priority]} · {n.fired_at}_")

    return {
        "topic": topic,
        "url": f"https://ntfy.sh/{topic}",
        "headers": {
            # Si algún cliente de ntfy mangle los acentos, éste es el único
            # punto donde hay que codificar el header (RFC 2047). El texto en
            # español no se degrada a ASCII aquí: se pierde información.
            "Title": n.title,
            "Priority": NTFY_PRIORITY[n.priority],
            "Tags": ",".join(NTFY_TAGS[n.trigger]),
            "Markdown": "yes",
        },
        "body": "\n".join(cuerpo),
        "dedup_key": n.dedup_key,
    }


def render_markdown(ns: list[Notification]) -> str:
    """Markdown para el step summary del cron y para notifications-latest.md."""
    L: list[str] = ["# Notificaciones", ""]

    if not ns:
        # El caso vacío no es un error ni un hueco: es la salida más frecuente y
        # la que confirma que el sistema funciona. Se imprime explícitamente
        # para que un día sin avisos se distinga de un día en que el paso falló.
        L.append("**Sin cambios de estado. Nada que avisar hoy.**")
        L.append("")
        L.append(
            "_Este motor sólo avisa de TRANSICIONES de la decisión, nunca de niveles ni de_"
            " _'oportunidades'. El silencio es el resultado esperado._"
        )
        return "\n".join(L)

    ordenes = sum(1 for n in ns if n.es_orden_ejecutable)
    L.append(f"**{len(ns)} aviso(s).** Ordenados por prioridad.")
    # Se dice explícitamente cuántos cuestan comisiones: es el único número por
    # el que el usuario debería decidir si abre la app hoy o no.
    L.append("")
    L.append(
        f"_{ordenes} de ellos contiene una orden que cuesta comisiones._"
        if ordenes
        else "_Ninguno contiene una orden que cueste comisiones._"
    )
    L.append("")
    for n in ns:
        L.append(f"## [{PRIORIDAD_ES[n.priority]}] {n.title}")
        L.append("")
        L.append(n.body)
        L.append("")
        L.append("**Por qué**")
        L.append("")
        L += [f"- {r}" for r in n.razonamiento]
        L.append("")
        L.append("**Qué hacer**")
        L.append("")
        L += [f"- {e}" for e in n.estrategia]
        L.append("")
        L.append(f"_{n.trigger} · {n.fired_at} · `{n.dedup_key}`_")
        L.append("")

    L.append("---")
    L.append("")
    L.append(
        "_Ningún aviso de este motor es un pronóstico de precio. Cada uno reporta un_"
        " _cambio de estado ya ocurrido en la decisión. No es asesoría en inversiones._"
    )
    return "\n".join(L)
