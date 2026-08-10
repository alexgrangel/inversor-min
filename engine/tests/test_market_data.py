"""
Parseo de venues contra respuestas GRABADAS de las APIs reales (10-ago-2026).
Cero red: los fixtures en tests/fixtures/ son JSON crudo capturado en vivo,
recortado a 15 filas. Las dos trampas documentadas en market_data.py:

  - Kraken: la llave del resultado es el código interno (XXBTZUSD), no el
    `pair` que mandaste (XBTUSD). Y "last" no es una serie.
  - Coinbase: el array es [time, low, high, open, close, volume] — NO es
    orden OHLC. El cierre es el índice 4; el 3 es el open. El fixture tiene
    open ≠ close en cada fila, así que confundir índices truena aquí.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import pytest

from inversor.sources import market_data as md

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(nombre: str) -> object:
    return json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))


# ---------------- Kraken ----------------


def test_kraken_usa_la_llave_interna_no_el_pair(monkeypatch):
    kr = _fixture("kraken_ohlc_btc.json")
    # La trampa es real en el fixture capturado: mandamos XBTUSD y la
    # respuesta viene bajo XXBTZUSD.
    assert "XBTUSD" not in kr["result"]
    assert "XXBTZUSD" in kr["result"]

    monkeypatch.setattr(md, "_get", lambda url, timeout=25: kr)
    serie = md.kraken_daily("BTC")

    filas = kr["result"]["XXBTZUSD"]
    assert len(serie) == len(filas)
    # cierre = índice 4 de cada fila, fecha = epoch UTC del índice 0
    assert serie[-1][1] == float(filas[-1][4])
    assert serie[-1][0] == datetime.fromtimestamp(
        int(filas[-1][0]), tz=timezone.utc
    ).date()


def test_kraken_ignora_last_sin_importar_el_orden(monkeypatch):
    # "last" primero en el dict: si el parseo tomara "la primera llave" a
    # secas, devolvería basura. Debe tomar la primera llave DISTINTA de last.
    fila = [1754870400, "64000.0", "65000.0", "63000.0", "64500.1", "64400", "100.5", 42]
    kr = {"error": [], "result": {"last": 1754870400, "XXBTZUSD": [fila]}}
    monkeypatch.setattr(md, "_get", lambda url, timeout=25: kr)
    serie = md.kraken_daily("BTC")
    assert serie == [(date(2025, 8, 11), 64500.1)]


def test_kraken_error_no_vacio_truena(monkeypatch):
    kr = {"error": ["EGeneral:Invalid arguments"], "result": {}}
    monkeypatch.setattr(md, "_get", lambda url, timeout=25: kr)
    with pytest.raises(md.MarketDataError, match="Kraken error"):
        md.kraken_daily("BTC")


def test_kraken_sin_serie_truena(monkeypatch):
    kr = {"error": [], "result": {"last": 123}}
    monkeypatch.setattr(md, "_get", lambda url, timeout=25: kr)
    with pytest.raises(md.MarketDataError, match="sin serie"):
        md.kraken_daily("BTC")


# ---------------- Coinbase ----------------


def test_coinbase_cierre_es_indice_4_no_orden_ohlc(monkeypatch):
    cb = _fixture("coinbase_candles_btc.json")
    # El fixture real tiene open (3) ≠ close (4) en todas las filas: si el
    # parseo asumiera orden OHLC (close en 3), esta comparación fallaría.
    assert all(r[3] != r[4] for r in cb)
    # Y low (1) <= open/close <= high (2): consistente con [t, low, high, o, c].
    assert all(r[1] <= r[3] <= r[2] and r[1] <= r[4] <= r[2] for r in cb)

    paginas = iter([cb, []])
    monkeypatch.setattr(md, "_get", lambda url, timeout=25: next(paginas))
    monkeypatch.setattr(md.time, "sleep", lambda s: None)
    serie = md.coinbase_daily("BTC")

    por_fecha = {
        datetime.fromtimestamp(int(r[0]), tz=timezone.utc).date(): float(r[4])
        for r in cb
    }
    assert dict(serie) == por_fecha
    # Orden ascendente por fecha, sin importar que Coinbase devuelva descendente.
    fechas = [f for f, _ in serie]
    assert fechas == sorted(fechas)


def test_coinbase_paginas_repetidas_terminan_en_vez_de_girar(monkeypatch):
    # Si el venue repite la misma página (sin avance hacia atrás), el guard
    # anti-bucle corta en vez de girar para siempre con limit > velas.
    cb = _fixture("coinbase_candles_btc.json")
    monkeypatch.setattr(md, "_get", lambda url, timeout=25: cb)
    monkeypatch.setattr(md.time, "sleep", lambda s: None)
    serie = md.coinbase_daily("BTC", limit=500)
    assert len(serie) == len({int(r[0]) for r in cb})


def test_coinbase_vacio_truena(monkeypatch):
    monkeypatch.setattr(md, "_get", lambda url, timeout=25: [])
    with pytest.raises(md.MarketDataError, match="sin velas"):
        md.coinbase_daily("BTC")


# ---------------- cascada ----------------


def _serie_larga(n: int = 500) -> list[tuple[date, float]]:
    d0 = date(2025, 3, 1)
    return [(d0 + timedelta(days=i), 60_000.0 + i) for i in range(n)]


def test_cascada_cae_al_siguiente_venue_y_registra_el_fallo(monkeypatch):
    def kraken_roto(asset, limit=500):
        raise md.MarketDataError("HTTP 520")

    monkeypatch.setitem(md.VENUES, "kraken", kraken_roto)
    monkeypatch.setitem(md.VENUES, "coinbase", lambda a, limit=500: _serie_larga())

    serie, venue, fallos = md.daily_closes("BTC")
    assert venue == "coinbase"
    assert len(serie) == 500
    assert len(fallos) == 1 and "kraken" in fallos[0] and "HTTP 520" in fallos[0]


def test_cascada_rechaza_series_cortas_como_fallo(monkeypatch):
    # 209 velas no alcanzan para clasificar régimen: cuenta como fallo y se
    # sigue al siguiente venue, no se acepta en silencio.
    monkeypatch.setitem(md.VENUES, "kraken", lambda a, limit=500: _serie_larga(209))
    monkeypatch.setitem(md.VENUES, "coinbase", lambda a, limit=500: _serie_larga(500))

    serie, venue, fallos = md.daily_closes("BTC")
    assert venue == "coinbase"
    assert "209" in fallos[0]


def test_cascada_truena_si_ningun_venue_sirve(monkeypatch):
    for nombre in md.ORDEN_POR_DEFECTO:
        monkeypatch.setitem(
            md.VENUES, nombre,
            lambda a, limit=500: (_ for _ in ()).throw(md.MarketDataError("caído")),
        )
    with pytest.raises(md.MarketDataError, match="Ningún venue"):
        md.daily_closes("BTC")
