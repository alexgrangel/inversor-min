"""
Sonda de venues para correr DESDE un runner de GitHub Actions (Prompt 2).

La hipótesis a comprobar: Binance devuelve HTTP 451 desde la IP estadounidense
del runner y Kraken no. El veredicto se decide por el primario:

  - Kraken OK desde CI  → exit 0: la arquitectura del cron es viable.
  - Kraken FALLA en CI  → exit 1: cambia la arquitectura, sin importar si
    Coinbase salvó la corrida. El diseño asume que el venue primario funciona.

Además sondea cada host de Binance POR SEPARADO: binance_daily() hace cascada
interna y esconde cuál host respondió qué. data-api.binance.vision "probablemente
funciona" según el foro de Binance — esto lo convierte en dato medido en vez de
supuesto.

Salida en markdown para pegarse directo en $GITHUB_STEP_SUMMARY.
"""
from __future__ import annotations

import sys
import urllib.error

from ..sources import market_data as md


def _sonda_venue(nombre: str) -> tuple[bool, str]:
    try:
        serie = md.VENUES[nombre]("BTC", 500)
        f, c = serie[-1]
        return True, f"OK — {len(serie)} velas, última {f} cierre {c:,.0f} USD"
    except Exception as e:  # noqa: BLE001 — la sonda reporta, no decide
        return False, f"{type(e).__name__}: {str(e)[:160]}"


def _sonda_host_binance(host: str) -> str:
    url = f"{host}/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=10"
    try:
        rows = md._get(url)
        n = len(rows) if isinstance(rows, list) else 0
        return f"OK — {n} filas"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {str(e)[:100]}"


def main() -> int:
    print("## Sonda de venues desde este runner\n")
    print("| venue | resultado |")
    print("|---|---|")
    ok: dict[str, bool] = {}
    for nombre in md.ORDEN_POR_DEFECTO:
        exito, msg = _sonda_venue(nombre)
        ok[nombre] = exito
        print(f"| {nombre} | {msg} |")

    print("\n### Binance por host (la cascada interna esconde cuál falló)\n")
    print("| host | resultado |")
    print("|---|---|")
    for host in ("https://data-api.binance.vision", "https://api.binance.com"):
        print(f"| {host} | {_sonda_host_binance(host)} |")

    print()
    if ok["kraken"]:
        print("**Veredicto: hipótesis confirmada** — el venue primario (Kraken)")
        print("funciona desde la IP del runner. La arquitectura del cron es viable.")
        return 0
    respaldo = " (Coinbase respondió, pero el diseño asume el primario)" if ok["coinbase"] else ""
    print(f"**⛔ Veredicto: Kraken NO es alcanzable desde CI{respaldo}.**")
    print("CAMBIA LA ARQUITECTURA antes de activar el cron diario.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
