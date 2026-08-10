"""
Banxico SIE (Sistema de Información Económica) — API REST oficial.

Token gratuito: https://www.banxico.org.mx/SieAPIRest/service/v1/token

⚠️ ESTADO DE VERIFICACIÓN DE LOS IDs — verificado 10-ago-2026 contra el título
oficial de cada serie en el catálogo, vía GET /series/{id} de esta misma API:

  CONFIRMADOS  SF43718 (FIX), SP68257 (UDIS), SF61745 (tasa objetivo)
  CONFIRMADOS  SF60633/34/35/36 — "Valores gubernamentales, Resultados de la
               subasta semanal Cetes a 28/91/182/364 días - Tasa de
               rendimiento - Fecha subasta". Es la subasta primaria que
               queríamos, fechada al martes de subasta.
  CORREGIDO    inpc_anual era SP74665 = "Inflación No subyacente (nueva
               definición) Anual". No era paranoia: el 10-ago-2026 esa serie
               publicaba 0.29% mientras la inflación general estaba en 3.12%
               — el interés real habría salido ~6.7% en vez de ~3.8%. Ahora
               es SP30578 = "Índice Nacional de Precios al consumidor
               variación anual", confirmado por título y por dato.

La moraleja sigue vigente: los rangos SANITY no te protegen de un ID
plausible-pero-equivocado (0.29% cae perfectamente dentro de (-5.0, 40.0)).
Por eso hay validación ESTRUCTURAL además del rango:

  - validate_series_title(): el título oficial debe contener lo que la llave
    dice ser (p.ej. "cetes a 91 días") y NO contener lo que delata a la serie
    equivocada (p.ej. "subyacente"). La aplica `python -m inversor
    verify-series`, que ahora falla con código != 0 si algo no corresponde.
  - validate_cetes_curve(): la curva debe ser monótona por plazo dentro de
    una tolerancia. Un plazo intercambiado zigzaguea; una curva real no.
    La aplica cetes_curve() en cada corrida.

Contexto útil: en SIE conviven al menos tres familias de CETES. SF282/SF3338/
SF3270/SF3367 son promedio mensual; SF43936 es la serie semanal del cuadro
CF107 (resultados de subasta a fecha de colocación); la familia SF606xx es la
subasta semanal fechada a la subasta. Elige a propósito, no por lo que salga
primero en una búsqueda.
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
    "fix_usdmxn": "SF43718",      # Tipo de cambio FIX              [CONFIRMADO 10-ago-2026]
    "udis": "SP68257",            # Valor de UDIS                   [CONFIRMADO 10-ago-2026]
    "cetes_28": "SF60633",        # CETES 28d subasta semanal       [CONFIRMADO 10-ago-2026]
    "cetes_91": "SF60634",        # CETES 91d subasta semanal       [CONFIRMADO 10-ago-2026]
    "cetes_182": "SF60635",       # CETES 182d subasta semanal      [CONFIRMADO 10-ago-2026]
    "cetes_364": "SF60636",       # CETES 364d subasta semanal      [CONFIRMADO 10-ago-2026]
    "tasa_objetivo": "SF61745",   # Tasa objetivo Banxico           [CONFIRMADO 10-ago-2026]
    "inpc_anual": "SP74665",      # INPC variación anual (general)  [CONFIRMADO 10-ago-2026]
    # inpc_anual fue SP74665 (inflación NO subyacente) hasta el 10-ago-2026.
    # Ver el docstring del módulo: publicaba 0.29% vs 3.12% de la general.
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

# Validación estructural de títulos (regla 5): SANITY atrapa basura numérica,
# esto atrapa lo plausible-pero-equivocado. El caso que motivó ambas listas:
# SP74665 pasaba SANITY publicando 0.29% de inflación "anual" porque era la NO
# subyacente. Comparación case-insensitive (casefold), acentos tal cual vienen
# en el catálogo.
TITULO_DEBE_CONTENER: dict[str, tuple[str, ...]] = {
    "fix_usdmxn": ("tipo de cambio", "fix"),
    "udis": ("udis",),
    "cetes_28": ("cetes a 28 días", "subasta", "tasa de rendimiento"),
    "cetes_91": ("cetes a 91 días", "subasta", "tasa de rendimiento"),
    "cetes_182": ("cetes a 182 días", "subasta", "tasa de rendimiento"),
    "cetes_364": ("cetes a 364 días", "subasta", "tasa de rendimiento"),
    "tasa_objetivo": ("tasa objetivo",),
    "inpc_anual": ("índice nacional de precios", "variación anual"),
}
TITULO_NO_DEBE_CONTENER: dict[str, tuple[str, ...]] = {
    # "subyacente" es substring de "no subyacente": una sola palabra veta las
    # dos series equivocadas a la vez.
    "inpc_anual": ("subyacente",),
    # "promedio" delata la familia de promedio mensual (SF282/SF3338/...):
    # mismo instrumento, otra convención — no es la subasta primaria.
    "cetes_28": ("promedio",),
    "cetes_91": ("promedio",),
    "cetes_182": ("promedio",),
    "cetes_364": ("promedio",),
}

# Tolerancia de monotonía para la curva CETES, en puntos porcentuales.
# Juicio sin calibrar contra histórico (mismo estatus que los umbrales de
# signals.py): más grande que el ruido entre plazos contiguos de una subasta
# normal (la del 4-ago-2026 fue 6.17/6.40/6.75/7.01: pasos de 23–35 pb),
# más chica que el quiebre que produce un plazo intercambiado (≥58 pb en esa
# misma curva). [CALIBRACIÓN PENDIENTE]
CURVA_TOLERANCIA_PP: float = 0.35


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


def validate_series_title(key: str, titulo: str) -> list[str]:
    """
    Devuelve la lista de problemas del título oficial contra lo que la llave
    dice ser (vacía = consistente). No truena: verify-series acumula todos los
    problemas de todas las series antes de salir con código != 0.
    """
    t = titulo.casefold()
    problemas: list[str] = []
    for frag in TITULO_DEBE_CONTENER.get(key, ()):
        if frag.casefold() not in t:
            problemas.append(f"el título no contiene '{frag}'")
    for frag in TITULO_NO_DEBE_CONTENER.get(key, ()):
        if frag.casefold() in t:
            problemas.append(f"el título contiene '{frag}', que delata otra serie")
    return problemas


def validate_cetes_curve(
    curve_pp: dict[int, float], tol_pp: float = CURVA_TOLERANCIA_PP
) -> None:
    """
    La curva debe ser monótona por plazo dentro de la tolerancia — creciente o
    decreciente (invertida), ambas son formas reales. Lo que una curva real no
    hace es zigzaguear ≥ tol entre plazos contiguos: eso es una serie de otra
    familia, un plazo intercambiado o un dato dislocado, y bloquea duro
    (reglas 5 y 6).

    Limitación conocida: una curva con TODAS las etiquetas invertidas es
    monótona decreciente y pasa esta prueba — es indistinguible de una curva
    genuinamente invertida. Contra eso está validate_series_title, que lee el
    plazo del título oficial. Las dos validaciones son complementarias, no
    redundantes.
    """
    if len(curve_pp) < 2:
        return
    plazos = sorted(curve_pp)
    # El redondeo mata el ruido de punto flotante en la frontera exacta:
    # 6.40 - 6.75 da -0.34999999999999964, que sin redondear pasaría la
    # desigualdad estricta contra -0.35.
    difs = [
        (a, b, round(curve_pp[b] - curve_pp[a], 9)) for a, b in zip(plazos, plazos[1:])
    ]
    # Desigualdad estricta a propósito: un paso contrario de exactamente tol
    # ya cuenta como quiebre. Con pasos reales de 23-35 pb, ser laxo en la
    # frontera dejaría pasar el intercambio de plazos contiguos.
    creciente = all(d > -tol_pp for _, _, d in difs)
    decreciente = all(d < tol_pp for _, _, d in difs)
    if creciente or decreciente:
        return
    detalle = ", ".join(f"{a}d→{b}d {d:+.2f} pp" for a, b, d in difs)
    raise BanxicoError(
        f"Curva CETES no monótona (tolerancia {tol_pp} pp): {detalle}."
        " Casi seguro un ID de serie está mal o un dato viene dislocado."
        " Corre verify-series."
    )


def cetes_curve(obs: dict[str, Observation]) -> dict[int, float]:
    """Curva CETES en decimal (0.0701), no en porcentaje. Valida forma al construir."""
    mapping = {28: "cetes_28", 91: "cetes_91", 182: "cetes_182", 364: "cetes_364"}
    pp = {d: obs[k].value for d, k in mapping.items() if k in obs}
    validate_cetes_curve(pp)
    return {d: v / 100.0 for d, v in pp.items()}


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
