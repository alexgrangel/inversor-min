"""
Banxico SIE (Sistema de Información Económica) — API REST oficial.

Token gratuito: https://www.banxico.org.mx/SieAPIRest/service/v1/token

⚠️ ESTADO DE VERIFICACIÓN DE LOS IDs (revisado 10-ago-2026 contra fuentes):

  CONFIRMADOS   SF43718 (FIX), SP68257 (UDIS), SF61745 (tasa objetivo)
  2ª MANO       SF60633 (CETES 28d) — corroborado por dos librerías, no por
                el catálogo oficial de Banxico
  SIN VERIFICAR SF60634 / SF60635 / SF60636 (CETES 91/182/364d). Cero fuentes.
  PROBABLEMENTE SP74665 NO es INPC general: es "Inflación NO SUBYACENTE anual".
  INCORRECTO    Usarlo sesga el cálculo de interés real y por tanto el ISR.

ANTES DE PONERLE UN PESO ENCIMA corre:

    python -m inversor verify-series

y confirma que el título de cada serie corresponde. Ojo: los rangos SANITY de
abajo NO te protegen de esto. Una serie de CETES con el plazo equivocado cae
igual dentro de (0.5, 30.0), y la inflación no subyacente cae dentro de
(-5.0, 40.0). SANITY atrapa basura, no atrapa lo plausible-pero-equivocado.

Contexto útil: en SIE conviven al menos tres familias de CETES. SF282/SF3338/
SF3270/SF3367 son promedio mensual; SF43936 es la serie semanal del cuadro
CF107 (resultados de subasta a fecha de colocación, que es lo que significa
"mercado primario"); la familia SF606xx es un set diario distinto. Elige a
propósito, no por lo que salga primero en una búsqueda.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta

BASE = "https://www.banxico.org.mx/SieAPIRest/service/v1"

SERIES: dict[str, str] = {
    "fix_usdmxn": "SF43718",      # Tipo de cambio FIX             [CONFIRMADO]
    "udis": "SP68257",            # Valor de UDIS                  [CONFIRMADO]
    "cetes_28": "SF60633",        # CETES 28d                      [2ª MANO]
    "cetes_91": "SF60634",        # CETES 91d                      [SIN VERIFICAR]
    "cetes_182": "SF60635",       # CETES 182d                     [SIN VERIFICAR]
    "cetes_364": "SF60636",       # CETES 364d                     [SIN VERIFICAR]
    "tasa_objetivo": "SF61745",   # Tasa objetivo Banxico          [CONFIRMADO]
    "inpc_anual": "SP74665",      # ⚠️ es NO SUBYACENTE, no general [CORREGIR]
}

# Límites documentados de la API: máximo 20 series por request,
# 80 requests/minuto, 40,000/día. El token se acepta en el header
# 'Bmx-Token' (funciona en la práctica) y como query param '?token='
# (esta última es la documentada por ejemplo en el portal de Banxico).

# Rangos de cordura. Si un dato sale de aquí, es un ID equivocado o basura.
SANITY: dict[str, tuple[float, float]] = {
    "fix_usdmxn": (10.0, 40.0),
    "udis": (5.0, 20.0),
    "cetes_28": (0.5, 30.0),
    "cetes_91": (0.5, 30.0),
    "cetes_182": (0.5, 30.0),
    "cetes_364": (0.5, 30.0),
    "tasa_objetivo": (0.5, 30.0),
    "inpc_anual": (-5.0, 40.0),
}


class BanxicoError(RuntimeError):
    pass


@dataclass(frozen=True)
class Observation:
    key: str
    series_id: str
    value: float
    as_of: date
    stale_days: int


def _request(path: str, token: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}",
        headers={"Bmx-Token": token, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise BanxicoError(f"HTTP {e.code} en {path}: {e.read().decode('utf-8')[:300]}") from e
    except Exception as e:  # noqa: BLE001
        raise BanxicoError(f"Fallo de red en {path}: {e}") from e


def _parse_dato(d: dict) -> tuple[date, float] | None:
    raw = d.get("dato", "").replace(",", "").strip()
    if raw in ("", "N/E", "N/A"):
        return None
    return datetime.strptime(d["fecha"], "%d/%m/%Y").date(), float(raw)


def fetch_latest(keys: list[str], token: str, today: date | None = None) -> dict[str, Observation]:
    """
    Trae el último dato disponible de cada serie.

    Usa /datos/oportuno (último publicado). Series de subasta como CETES sólo
    se publican los jueves; INPC es quincenal/mensual. La antigüedad se reporta
    siempre y quien decide qué hacer con ella es decide.py, no esta capa.
    """
    today = today or date.today()
    ids = [SERIES[k] for k in keys]
    payload = _request(f"/series/{','.join(ids)}/datos/oportuno", token)

    by_id: dict[str, tuple[date, float]] = {}
    for s in payload.get("bmx", {}).get("series", []):
        datos = s.get("datos") or []
        if not datos:
            continue
        parsed = _parse_dato(datos[-1])
        if parsed:
            by_id[s["idSerie"]] = parsed

    out: dict[str, Observation] = {}
    missing: list[str] = []
    for k in keys:
        sid = SERIES[k]
        if sid not in by_id:
            missing.append(f"{k}({sid})")
            continue
        d, v = by_id[sid]
        lo, hi = SANITY[k]
        if not (lo <= v <= hi):
            raise BanxicoError(
                f"Serie '{k}' ({sid}) devolvió {v}, fuera del rango de cordura [{lo}, {hi}]."
                " Casi seguro el ID de serie está mal. Corre verify_series."
            )
        out[k] = Observation(k, sid, v, d, (today - d).days)

    if missing:
        raise BanxicoError(f"Sin datos para: {', '.join(missing)}")
    return out


def fetch_history(key: str, token: str, days: int = 400) -> list[tuple[date, float]]:
    end = date.today()
    start = end - timedelta(days=days)
    payload = _request(
        f"/series/{SERIES[key]}/datos/{start:%Y-%m-%d}/{end:%Y-%m-%d}", token
    )
    series = payload.get("bmx", {}).get("series", [])
    if not series:
        raise BanxicoError(f"Sin serie devuelta para {key}")
    rows = [_parse_dato(d) for d in series[0].get("datos", [])]
    return [r for r in rows if r is not None]


def get_token() -> str:
    tok = os.environ.get("BANXICO_TOKEN", "").strip()
    if not tok:
        raise BanxicoError(
            "Falta BANXICO_TOKEN. Consíguelo gratis en"
            " https://www.banxico.org.mx/SieAPIRest/service/v1/token"
        )
    return tok


def cetes_curve(obs: dict[str, Observation]) -> dict[int, float]:
    """Curva CETES en decimal (0.0701), no en porcentaje."""
    mapping = {28: "cetes_28", 91: "cetes_91", 182: "cetes_182", 364: "cetes_364"}
    return {d: obs[k].value / 100.0 for d, k in mapping.items() if k in obs}


def pick_hurdle_tenor(curve: dict[int, float], horizon_days: int) -> tuple[int, float]:
    """
    El hurdle es el CETES cuyo plazo mejor calza tu horizonte. No el más alto:
    tomar el 364d cuando tu horizonte es 30 días es asumir riesgo de tasa que
    la comparación no está midiendo.
    """
    if not curve:
        raise BanxicoError("Curva CETES vacía.")
    tenor = min(curve, key=lambda t: abs(t - horizon_days))
    return tenor, curve[tenor]
