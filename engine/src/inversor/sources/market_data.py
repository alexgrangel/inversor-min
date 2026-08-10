"""
Datos de mercado cripto — venue-neutral, sin autenticación, sin llaves.

POR QUÉ ESTE MÓDULO EXISTE Y REEMPLAZA A binance.py
====================================================
Binance bloquea el tráfico proveniente de Estados Unidos: `api.binance.com`
devuelve HTTP 451 desde una IP estadounidense. Los runners de GitHub Actions
son estadounidenses. Es decir: la arquitectura entera del cron —que es el
corazón del proyecto— no habría corrido ni una sola vez.

`data-api.binance.vision` *probablemente* funciona (es el host market-data-only
sin auth), pero Binance no documenta ninguna excepción geográfica para él y su
propio personal dice en el foro de desarrolladores que los servidores alojados
en EE.UU. no funcionan. Apostar la arquitectura a un "probablemente" no
documentado es exactamente el tipo de supuesto que este repo existe para evitar.

Orden de venues, y la razón de cada uno:

  1. KRAKEN (primario). Devuelve hasta ~720 velas diarias en UNA sola petición.
     El motor necesita 210 mínimo y 500 idealmente para clasificar régimen, así
     que Kraken lo resuelve sin paginar — y no paginar es no tener bugs de
     paginación. Sin llave. Verificado en vivo.
  2. COINBASE EXCHANGE (respaldo). Tope de ~300 velas por petición, así que
     requiere paginar para llegar a 500. Sin llave. Verificado en vivo.
     Límite documentado: 10 req/s por IP.
  3. BINANCE (último recurso). Se conserva sólo para correr desde una máquina
     no estadounidense — tu Mac, por ejemplo. En CI va a fallar con 451.

Los tres devuelven `(fecha, cierre)` para que decide() pueda verificar frescura.
Descartar los timestamps —como hacía la versión anterior— hace que una serie
congelada sea indistinguible de una fresca, que es justo lo que la regla 4 de
CLAUDE.md prohíbe.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

# Activos canónicos. NO son pares de un exchange: cada venue traduce.
# Antes el universo decía "BTCUSDT", que es un par de Binance, y el snapshot
# publicaba ese nombre aunque el precio viniera de otro lado. Etiquetar el dato
# con el nombre del venue equivocado es una mentira pequeña que se vuelve grande
# cuando alguien audita el log walk-forward dentro de un año.
VENUE_SYMBOLS: dict[str, dict[str, str]] = {
    "kraken":   {"BTC": "XBTUSD",  "ETH": "ETHUSD"},
    "coinbase": {"BTC": "BTC-USD", "ETH": "ETH-USD"},
    "binance":  {"BTC": "BTCUSDT", "ETH": "ETHUSDT"},
}

USER_AGENT = "inversor-min/1.0 (personal finance tool; contact via repo)"
TIMEOUT = 25


class MarketDataError(RuntimeError):
    pass


def _get(url: str, timeout: int = TIMEOUT) -> object:
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# --------------------------------------------------------------------------
# Kraken — primario
# --------------------------------------------------------------------------

def kraken_daily(asset: str, limit: int = 500) -> list[tuple[date, float]]:
    """
    `https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440`

    Respuesta: {"error": [], "result": {"XXBTZUSD": [[time,o,h,l,c,vwap,vol,n]],
                                        "last": 1234}}

    Trampa: la llave del resultado es el código interno de Kraken (`XXBTZUSD`),
    NO el `pair` que mandaste. Jamás la escribas a mano: toma la primera llave
    distinta de "last".
    """
    pair = VENUE_SYMBOLS["kraken"][asset]
    d = _get(f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval=1440")
    if not isinstance(d, dict):
        raise MarketDataError(f"Kraken devolvió algo que no es un objeto para {pair}")
    if d.get("error"):
        raise MarketDataError(f"Kraken error para {pair}: {d['error']}")
    result = d.get("result") or {}
    keys = [k for k in result if k != "last"]
    if not keys:
        raise MarketDataError(f"Kraken sin serie para {pair} (llaves: {list(result)})")
    rows = result[keys[0]]
    out = [
        (datetime.fromtimestamp(int(r[0]), tz=timezone.utc).date(), float(r[4]))
        for r in rows
    ]
    return out[-limit:]


# --------------------------------------------------------------------------
# Coinbase Exchange — respaldo
# --------------------------------------------------------------------------

def coinbase_daily(asset: str, limit: int = 500) -> list[tuple[date, float]]:
    """
    `https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400`

    Respuesta: [[time, low, high, open, close, volume], ...] — OJO, el orden NO
    es OHLC: es `low, high, open, close`. La documentación de Coinbase es
    célebre por confundir esto. El cierre es el índice 4 (igual que en Kraken,
    por casualidad, no por diseño).

    Tope ~300 velas por petición ⇒ hay que paginar con start/end ISO-8601.
    Límite documentado: 10 req/s por IP; el sleep de abajo es cortesía barata.
    """
    product = VENUE_SYMBOLS["coinbase"][asset]
    base = f"https://api.exchange.coinbase.com/products/{product}/candles?granularity=86400"
    seen: dict[date, float] = {}
    end = datetime.now(tz=timezone.utc)

    while len(seen) < limit:
        start = end.timestamp() - 300 * 86400
        start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
        url = f"{base}&start={start_dt.isoformat()}&end={end.isoformat()}"
        rows = _get(url)
        if not isinstance(rows, list) or not rows:
            break
        for r in rows:
            seen.setdefault(
                datetime.fromtimestamp(int(r[0]), tz=timezone.utc).date(), float(r[4])
            )
        oldest = min(int(r[0]) for r in rows)
        nuevo_end = datetime.fromtimestamp(oldest - 1, tz=timezone.utc)
        if nuevo_end >= end:      # sin avance ⇒ cortar en vez de girar para siempre
            break
        end = nuevo_end
        time.sleep(0.15)

    if not seen:
        raise MarketDataError(f"Coinbase sin velas para {product}")
    return sorted(seen.items())[-limit:]


# --------------------------------------------------------------------------
# Binance — último recurso, falla con 451 desde EE.UU.
# --------------------------------------------------------------------------

def binance_daily(asset: str, limit: int = 500) -> list[tuple[date, float]]:
    symbol = VENUE_SYMBOLS["binance"][asset]
    hosts = ("https://data-api.binance.vision", "https://api.binance.com")
    last: Exception | None = None
    for host in hosts:
        try:
            rows = _get(f"{host}/api/v3/klines?symbol={symbol}&interval=1d&limit={min(limit,1000)}")
            if isinstance(rows, list) and rows:
                return [
                    (datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).date(), float(k[4]))
                    for k in rows
                ]
        except urllib.error.HTTPError as e:
            if e.code == 451:
                last = MarketDataError(
                    f"{host} → HTTP 451: bloqueo geográfico. Los runners de GitHub"
                    " Actions tienen IP de EE.UU. Usa Kraken o Coinbase."
                )
                continue
            last = MarketDataError(f"{host} → HTTP {e.code}")
        except Exception as e:  # noqa: BLE001
            last = e
    raise MarketDataError(f"Binance inalcanzable para {symbol}: {last}")


# --------------------------------------------------------------------------
# Fachada con cascada
# --------------------------------------------------------------------------

VENUES = {"kraken": kraken_daily, "coinbase": coinbase_daily, "binance": binance_daily}
ORDEN_POR_DEFECTO = ("kraken", "coinbase", "binance")


def daily_closes(
    asset: str, limit: int = 500, orden: tuple[str, ...] = ORDEN_POR_DEFECTO
) -> tuple[list[tuple[date, float]], str, list[str]]:
    """
    Devuelve (serie, venue_usado, intentos_fallidos).

    Deliberadamente NO silencia los fallos: el venue que sirvió el dato y los que
    fallaron van al snapshot. Si mañana la serie cambia de venue, el log
    walk-forward tiene que poder mostrar dónde ocurrió el corte — un cambio de
    fuente de precios es una discontinuidad en los datos, no un detalle de
    infraestructura.
    """
    fallos: list[str] = []
    for nombre in orden:
        try:
            serie = VENUES[nombre](asset, limit)
            if len(serie) < 210:
                fallos.append(f"{nombre}: sólo {len(serie)} velas, se requieren 210")
                continue
            return serie, nombre, fallos
        except Exception as e:  # noqa: BLE001
            fallos.append(f"{nombre}: {type(e).__name__}: {e}")
    raise MarketDataError(
        "Ningún venue devolvió una serie utilizable. Intentos:\n  " + "\n  ".join(fallos)
    )
