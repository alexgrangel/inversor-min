"""
Entrega de avisos a ntfy.sh desde CI (Prompt 4).

Uso: python -m inversor.scripts.ntfy_push <ruta a notifications-latest.json>

El topic viene de la variable de entorno NTFY_TOPIC (secreto del repo: un
topic de ntfy es público para quien lo adivine — regla 2 aplicada al canal de
avisos). Sin topic configurado la entrega se omite con nota y exit 0: la
entrega es opcional, el log committeado es la fuente de verdad.

Este script corre DESPUÉS del commit del snapshot, a propósito: un aviso
entregado al teléfono cuyo estado de cooldown no quedó persistido volvería a
dispararse en la corrida siguiente — el anti-spam depende de ese orden.

render_ntfy (notify_sinks) arma el payload y no manda nada; aquí vive el
transporte, que por eso no puede probarse sin red — lo testeable (mapeo de
prioridad, rehidratación, codificación de headers) está en funciones puras.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from ..notify import Notification
from ..notify_sinks import render_ntfy

# Un notifications-latest.json más viejo que esto no se entrega: si el engine
# hubiera corrido hoy, el archivo sería de hoy. Entregar uno rancio significa
# re-mandar los avisos de una corrida anterior (fue un bug real: el job podía
# quedar verde sin correr el engine y este paso re-posteaba lo de ayer).
MAX_EDAD_HORAS = 24.0

# Backoff antes del 2º y 3er intento de POST. Un aviso ya committeado que no
# llega al teléfono no se puede re-entregar después (el re-run del job no
# re-evalúa), así que los reintentos aquí son la única defensa contra un
# timeout transitorio de ntfy.sh.
REINTENTOS_BACKOFF_S: tuple[float, ...] = (2.0, 5.0)


def encode_header(valor: str) -> str:
    """
    RFC 2047 para headers no-ASCII. urllib codifica headers como latin-1 y
    truena con "→" (los títulos reales traen flechas y acentos); ntfy
    documenta soporte de =?UTF-8?B?...?= precisamente para esto.
    """
    try:
        valor.encode("ascii")
        return valor
    except UnicodeEncodeError:
        b64 = base64.b64encode(valor.encode("utf-8")).decode("ascii")
        return f"=?UTF-8?B?{b64}?="


def rehidratar(payload: dict) -> list[Notification]:
    """notifications-latest.json → Notification. Sólo los avisos emitidos:
    los suprimidos son auditoría, no se entregan."""
    return [Notification(**n) for n in payload.get("notifications", [])]


def _post(payload: dict) -> int:
    req = urllib.request.Request(
        payload["url"],
        data=payload["body"].encode("utf-8"),
        headers={k: encode_header(v) for k, v in payload["headers"].items()},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status


def entregar(payload: dict) -> int:
    """_post con reintentos. Devuelve el status HTTP del intento que pegó."""
    for i, espera in enumerate((*REINTENTOS_BACKOFF_S, None)):
        try:
            return _post(payload)
        except Exception:  # noqa: BLE001
            if espera is None:
                raise
            time.sleep(espera)
    raise AssertionError("inalcanzable")


def es_rancio(generated_at: str | None, ahora: datetime | None = None) -> float | None:
    """Horas de antigüedad si excede MAX_EDAD_HORAS; None si está fresco."""
    if not generated_at:
        return None
    ahora = ahora or datetime.now(timezone.utc)
    edad_h = (ahora - datetime.fromisoformat(generated_at)).total_seconds() / 3600.0
    return edad_h if edad_h > MAX_EDAD_HORAS else None


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("uso: python -m inversor.scripts.ntfy_push <notifications-latest.json>")
        return 64
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        print("[ntfy] NTFY_TOPIC no configurado; entrega omitida.")
        return 0
    ruta = Path(argv[1])
    if not ruta.exists():
        # Corrida --no-notify o primera corrida fallida antes del paso de
        # avisos: no hay archivo, no hay nada que entregar.
        print(f"[ntfy] {ruta} no existe; nada que entregar.")
        return 0
    data = json.loads(ruta.read_text(encoding="utf-8"))
    edad = es_rancio(data.get("generated_at"))
    if edad is not None:
        print(
            f"[ntfy] {ruta.name} es de hace {edad:.0f} horas: no se re-entrega una"
            " corrida anterior. ¿El engine corrió de verdad hoy?",
            file=sys.stderr,
        )
        return 1
    ns = rehidratar(data)
    if not ns:
        print("[ntfy] 0 avisos; el silencio no se entrega.")
        return 0

    fallos = 0
    for n in ns:
        p = render_ntfy(n, topic)
        try:
            status = entregar(p)
            print(f"[ntfy] {n.trigger} [{n.priority}] → HTTP {status}")
        except Exception as e:  # noqa: BLE001 — un aviso caído no debe callar al resto
            fallos += 1
            print(f"[ntfy] {n.trigger} FALLÓ: {type(e).__name__}: {e}", file=sys.stderr)
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
