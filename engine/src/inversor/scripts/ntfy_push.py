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
import urllib.request
from pathlib import Path

from ..notify import Notification
from ..notify_sinks import render_ntfy


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
    ns = rehidratar(json.loads(ruta.read_text(encoding="utf-8")))
    if not ns:
        print("[ntfy] 0 avisos; el silencio no se entrega.")
        return 0

    fallos = 0
    for n in ns:
        p = render_ntfy(n, topic)
        try:
            status = _post(p)
            print(f"[ntfy] {n.trigger} [{n.priority}] → HTTP {status}")
        except Exception as e:  # noqa: BLE001 — un aviso caído no debe callar al resto
            fallos += 1
            print(f"[ntfy] {n.trigger} FALLÓ: {type(e).__name__}: {e}", file=sys.stderr)
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
