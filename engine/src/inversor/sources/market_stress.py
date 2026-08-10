"""
Indicadores de estrés de mercado. Endpoints públicos, sin llaves de exchange.

Estos indicadores miden el ESTADO ACTUAL del mercado, no su futuro. Nada de
aquí entra a un modelo de precio (CLAUDE.md regla 1). Su único uso legítimo es
*recortar* tamaño vía `signals.combinar`. Ninguna lectura de este módulo puede
aumentar una posición ni disparar una compra: esa asimetría se impone en
`signals.py`, no aquí, pero conviene tenerla presente al leer este archivo.

⚠️ ESTADO DE VERIFICACIÓN DE LOS ENDPOINTS (revisado 10-ago-2026, en vivo):

  CONFIRMADO   alternative.me /fng/          — sin llave, JSON, campos como abajo
  CONFIRMADO   deribit /public/get_volatility_index_data — sin auth, JSON-RPC 2.0
  CONFIRMADO   FRED /fred/series/observations — requiere llave gratuita
  CONFIRMADO   series FRED: VIXCLS, DTWEXBGS, DGS10

Dos trampas ya verificadas y codificadas:

  1. Deribit devuelve `result.data` como lista de ARREGLOS
     `[timestamp_ms, open, high, low, close]`, no de objetos. Si algún día
     cambian a objetos, `_dvol_ultimo_cierre` truena en vez de leer basura.
  2. En FRED NO existe el DXY de ICE. DTWEXBGS es el índice amplio del dólar
     de la Fed, es OTRO índice (base ene-2006 = 100) y publica con ~2 días
     hábiles de retraso. Comparar su nivel contra "el DXY" es un error de
     unidades, no un detalle.

Los rangos SANITY de abajo atrapan basura (ID equivocado, HTML de error
parseado como número), no atrapan lo plausible-pero-equivocado. Igual que en
banxico.py: existen para que una serie mal identificada truene en vez de
producir un recorte de posición sobre un número inventado.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

FNG_BASE = "https://api.alternative.me/fng/"
DERIBIT_BASE = "https://www.deribit.com/api/v2/public"
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Varios servicios públicos (GDELT el primero) estrangulan clientes anónimos.
# Un User-Agent descriptivo no es cortesía: es la diferencia entre 200 y 429.
# INVERSOR_CONTACT es opcional; si lo defines, que sea un correo tuyo de verdad.
def user_agent() -> str:
    contacto = os.environ.get("INVERSOR_CONTACT", "").strip()
    sufijo = f"; contacto: {contacto}" if contacto else ""
    return f"inversor-min/1.0 (motor de decision personal; read-only{sufijo})"


USER_AGENT = user_agent()

# Series de FRED usadas. El ID va explícito para que un cambio sea visible en
# el diff, no escondido en un f-string.
FRED_SERIES: dict[str, str] = {
    "vix": "VIXCLS",            # VIX cierre diario                   [CONFIRMADO]
    "dolar_amplio": "DTWEXBGS",  # Índice amplio del dólar (Fed)      [CONFIRMADO]
    "treasury_10y": "DGS10",     # Rendimiento del bono a 10 años     [CONFIRMADO]
}

# Rangos de cordura. Fuera de esto es un ID equivocado o basura parseada.
SANITY: dict[str, tuple[float, float]] = {
    "fear_greed": (0.0, 100.0),      # el índice está definido en 0..100
    "dvol_btc": (5.0, 300.0),        # vol implícita anualizada en puntos
    "dvol_eth": (5.0, 300.0),
    "vix": (5.0, 150.0),             # mínimo histórico ~8.5, máximo intradía ~89
    "dolar_amplio": (80.0, 200.0),   # base ene-2006 = 100
    "treasury_10y": (-1.0, 25.0),    # negativo es improbable en USD, no imposible
}

# Antigüedad máxima tolerable por indicador, en días naturales. No son datos:
# son juicios sobre la cadencia de publicación de cada fuente, por eso viven
# nombrados y juntos. F&G es diario; FRED publica en días hábiles y DTWEXBGS
# arrastra ~2 días hábiles, así que un fin de semana largo lo pone en 5.
MAX_STALE_DIAS: dict[str, int] = {
    "fear_greed": 2,
    "dvol_btc": 2,
    "dvol_eth": 2,
    "vix": 5,
    "dolar_amplio": 7,
    "treasury_10y": 5,
}


class StressError(RuntimeError):
    """Fallo duro: el dato existe pero no es usable (rango, forma, red)."""


class StressUnavailable(StressError):
    """
    La fuente no está disponible (sin llave, sin red, sin datos).

    Se distingue de StressError porque `recolectar` la traduce a un renglón de
    `fuentes_no_disponibles`. Que una fuente de estrés no responda NUNCA se
    lee como "el mercado está tranquilo".
    """


@dataclass(frozen=True)
class StressReading:
    key: str
    source: str
    series_id: str
    value: float
    as_of: date
    stale_days: int
    label: str = ""

    @property
    def stale(self) -> bool:
        return self.stale_days > MAX_STALE_DIAS.get(self.key, 5)


def _get_json(url: str, timeout: int = 20, redact: str = "") -> dict:
    """
    GET + JSON. `redact` es la llave de API: nunca debe aparecer en un mensaje
    de error, porque los errores acaban en el snapshot que es público.
    """
    def _safe(s: str) -> str:
        return s.replace(redact, "***") if redact else s

    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        raise StressUnavailable(_safe(f"HTTP {e.code} en {url}: {body}")) from e
    except Exception as e:  # noqa: BLE001
        raise StressUnavailable(_safe(f"Fallo de red en {url}: {e}")) from e

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        # Respuesta no-JSON = casi siempre una página de error o un captcha.
        raise StressUnavailable(_safe(f"Respuesta no-JSON de {url}: {raw[:120]!r}")) from e
    if not isinstance(payload, dict):
        raise StressUnavailable(_safe(f"Respuesta con forma inesperada de {url}"))
    return payload


def _check_sanity(key: str, value: float) -> float:
    lo, hi = SANITY[key]
    if value != value or not (lo <= value <= hi):  # value != value atrapa NaN
        raise StressError(
            f"Indicador '{key}' devolvió {value}, fuera del rango de cordura [{lo}, {hi}]."
            " Casi seguro cambió la forma de la respuesta o el ID de serie. No se usa."
        )
    return value


# ---------------------------------------------------------------- Fear & Greed

def fetch_fear_greed(limit: int = 1, today: date | None = None) -> StressReading:
    """
    Crypto Fear & Greed de alternative.me. Sin llave.

    Forma verificada: data[].value es STRING ("40"), data[].timestamp es
    epoch en segundos también como STRING. Se actualiza una vez al día
    ~00:00 UTC, así que 1 día de antigüedad es normal y 3 ya es sospechoso.

    OJO CON LA INTERPRETACIÓN: miedo extremo NO predice rebote. Aquí se usa
    sólo para recortar tamaño, porque coincide con los periodos donde una
    cuenta chica más necesita no estar apalancada al humor del mercado.
    """
    today = today or date.today()
    url = f"{FNG_BASE}?{urllib.parse.urlencode({'limit': limit, 'format': 'json'})}"
    payload = _get_json(url)

    data = payload.get("data") or []
    if not isinstance(data, list) or not data:
        raise StressUnavailable("alternative.me devolvió 'data' vacío.")
    row = data[0]
    if not isinstance(row, dict) or "value" not in row or "timestamp" not in row:
        raise StressUnavailable(f"Forma inesperada en alternative.me: {str(row)[:120]}")

    try:
        value = float(str(row["value"]).strip())
        ts = int(str(row["timestamp"]).strip())
    except (TypeError, ValueError) as e:
        raise StressError(f"No se pudo parsear F&G: {str(row)[:120]}") from e

    as_of = datetime.fromtimestamp(ts, tz=timezone.utc).date()
    return StressReading(
        key="fear_greed",
        source="alternative.me",
        series_id="fng",
        value=_check_sanity("fear_greed", value),
        as_of=as_of,
        stale_days=(today - as_of).days,
        label=str(row.get("value_classification", "")).strip(),
    )


# ---------------------------------------------------------------------- DVOL

def fetch_dvol(currency: str = "BTC", dias: int = 30, today: date | None = None) -> StressReading:
    """
    DVOL de Deribit: volatilidad implícita a 30 días del subyacente cripto.

    JSON-RPC 2.0. `result.data` es lista de ARREGLOS
    [timestamp_ms, open, high, low, close] — verificado en vivo. Se toma el
    CIERRE de la última barra diaria.

    Sólo BTC y ETH tienen índice DVOL. Pedir otra divisa devuelve error de la
    API, así que se rechaza antes de gastar el request.
    """
    cur = currency.upper().strip()
    if cur not in ("BTC", "ETH"):
        raise ValueError("DVOL sólo existe para BTC y ETH.")
    today = today or date.today()

    start_ms, end_ms = ventana_utc(dias, today)
    qs = urllib.parse.urlencode(
        {
            "currency": cur,
            "start_timestamp": start_ms,
            "end_timestamp": end_ms,
            "resolution": "1D",
        }
    )
    payload = _get_json(f"{DERIBIT_BASE}/get_volatility_index_data?{qs}")

    if "error" in payload:
        raise StressUnavailable(f"Deribit JSON-RPC error: {str(payload['error'])[:160]}")
    ts_ms, close = _dvol_ultimo_cierre(payload)

    key = f"dvol_{cur.lower()}"
    as_of = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date()
    return StressReading(
        key=key,
        source="deribit",
        series_id=f"DVOL_{cur}",
        value=_check_sanity(key, close),
        as_of=as_of,
        stale_days=(today - as_of).days,
        label="volatilidad implícita 30d",
    )


def _dvol_ultimo_cierre(payload: dict) -> tuple[int, float]:
    """
    Extrae (timestamp_ms, close) de la última barra.

    Está aparte y es estricto a propósito: si Deribit cambia de arreglos a
    objetos, esto truena con un mensaje legible en vez de que `row[4]` levante
    un IndexError críptico tres capas más arriba.
    """
    data = (payload.get("result") or {}).get("data")
    if not isinstance(data, list) or not data:
        raise StressUnavailable("Deribit devolvió result.data vacío.")
    row = data[-1]
    if not isinstance(row, (list, tuple)) or len(row) < 5:
        raise StressError(
            f"Deribit cambió la forma de result.data (esperaba [ts,o,h,l,c]): {str(row)[:120]}"
        )
    try:
        return int(row[0]), float(row[4])
    except (TypeError, ValueError) as e:
        raise StressError(f"Barra de DVOL no parseable: {str(row)[:120]}") from e


# ----------------------------------------------------------------------- FRED

def fred_api_key() -> str | None:
    """
    Llave gratuita de FRED. Devuelve None en vez de tronar: FRED es opcional
    y su ausencia debe degradar a "fuente no disponible", que en signals.py
    RECORTA tamaño. Nunca es un default silencioso ni un pase libre.
    """
    key = os.environ.get("FRED_API_KEY", "").strip()
    return key or None


def fetch_fred(key: str, api_key: str | None = None, today: date | None = None) -> StressReading:
    """
    Última observación disponible de una serie de FRED.

    Se piden varias observaciones en orden descendente y se toma la primera
    con valor real: FRED marca los huecos (feriados, días sin dato) con "."
    y tomar limit=1 a ciegas devolvería un punto vacío en cada puente.
    """
    if key not in FRED_SERIES:
        raise ValueError(f"Serie FRED desconocida: {key}. Conocidas: {sorted(FRED_SERIES)}")
    today = today or date.today()
    api_key = api_key or fred_api_key()
    if not api_key:
        raise StressUnavailable(
            "Falta FRED_API_KEY (gratuita en https://fredaccount.stlouisfed.org/apikeys)."
            " Se omite FRED; su ausencia se reporta, no se sustituye por un default."
        )

    series_id = FRED_SERIES[key]
    qs = urllib.parse.urlencode(
        {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 12,
        }
    )
    payload = _get_json(f"{FRED_BASE}?{qs}", redact=api_key)

    obs = payload.get("observations")
    if not isinstance(obs, list) or not obs:
        raise StressUnavailable(f"FRED devolvió 0 observaciones para {series_id}.")

    for row in obs:
        if not isinstance(row, dict):
            continue
        raw = str(row.get("value", "")).strip()
        if raw in ("", "."):  # "." es el marcador de hueco de FRED
            continue
        try:
            value = float(raw)
            as_of = datetime.strptime(str(row["date"]), "%Y-%m-%d").date()
        except (KeyError, TypeError, ValueError) as e:
            raise StressError(f"Observación FRED no parseable: {str(row)[:120]}") from e
        return StressReading(
            key=key,
            source="fred",
            series_id=series_id,
            value=_check_sanity(key, value),
            as_of=as_of,
            stale_days=(today - as_of).days,
        )

    raise StressUnavailable(
        f"FRED {series_id}: las últimas {len(obs)} observaciones vienen vacías."
    )


# ------------------------------------------------------------------ recolector

def recolectar(
    indicadores: tuple[str, ...] = ("fear_greed", "dvol_btc", "vix"),
    today: date | None = None,
) -> tuple[dict[str, StressReading], list[str]]:
    """
    Trae lo que se pueda y reporta explícitamente lo que no.

    Este es el ÚNICO try/except amplio del módulo y no contradice la regla de
    "nada de try/except que se trague errores" (CLAUDE.md, sección Estilo):
    no se traga nada. Convierte cada fallo en un renglón de
    `fuentes_no_disponibles`, que `signals.combinar` usa para RECORTAR tamaño.
    Un feed de estrés caído es incertidumbre sobre el estado del mundo, y la
    incertidumbre se paga con menos posición, no con la misma.

    Devuelve (lecturas, no_disponibles).
    """
    today = today or date.today()
    lecturas: dict[str, StressReading] = {}
    caidas: list[str] = []

    for ind in indicadores:
        try:
            if ind == "fear_greed":
                r = fetch_fear_greed(today=today)
            elif ind.startswith("dvol_"):
                r = fetch_dvol(ind.split("_", 1)[1].upper(), today=today)
            elif ind in FRED_SERIES:
                r = fetch_fred(ind, today=today)
            else:
                raise ValueError(f"Indicador desconocido: {ind}")
        except StressError as e:
            caidas.append(f"{ind}: {e}")
            continue

        # Rancio = no disponible. Regla 4: nunca se usa el último valor conocido
        # en silencio sólo porque llegó un 200.
        if r.stale:
            caidas.append(
                f"{ind}: dato de {r.as_of.isoformat()}, {r.stale_days} días de antigüedad"
                f" (límite {MAX_STALE_DIAS.get(ind, 5)})."
            )
            continue
        lecturas[ind] = r

    return lecturas, caidas


def ventana_utc(dias: int, today: date | None = None) -> tuple[int, int]:
    """Ventana [inicio, fin] en epoch-ms UTC. Aislada para poder testearla."""
    today = today or date.today()
    fin = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    inicio = fin - timedelta(days=dias)
    return int(inicio.timestamp() * 1000), int(fin.timestamp() * 1000)
