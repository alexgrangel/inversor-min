"""
Noticias. Este módulo NO hace sentiment y no va a hacerlo (CLAUDE.md regla 1).

Tiene exactamente dos salidas y ninguna más:

  (a) `volumen_anomalo`     — ¿el volumen de cobertura sobre un set de palabras
                              está estadísticamente elevado contra su propia
                              línea base? Sirve sólo para CORROBORAR estrés que
                              ya vieron los indicadores de mercado. No es una
                              señal por sí sola y jamás aumenta tamaño.
  (b) `ruptura_estructural` — ¿apareció un evento REGULATORIO que invalida el
                              modelo, en vez de mover el precio? Eso levanta un
                              BLOQUEO que exige revisión humana.

La distinción es toda la tesis del módulo. "Bitcoin cae 12%" no es información
para este sistema: el dimensionamiento por vol ya lo absorbió. "La CNBV
suspende operaciones de activos virtuales en instituciones de tecnología
financiera" sí lo es, porque invalida los supuestos del venue, del régimen
fiscal o de la posibilidad misma de tener la posición.

⚠️ ESTADO DE VERIFICACIÓN DE LOS ENDPOINTS (revisado 10-ago-2026, en vivo):

  CONFIRMADO   expansion.mx/rss                       RSS 2.0, es-mx, sin gzip
  CONFIRMADO   elfinanciero.com.mx/arc/outboundfeeds  Arc XP, RESPUESTA GZIPPED
  CONFIRMADO   bloomberglinea.com/arc/outboundfeeds   Arc XP, RESPUESTA GZIPPED
  CONFIRMADO   GDELT DOC 2.0 responde, y estrangula agresivo: 429 y luego 500
               en una prueba en vivo de hoy.
  SIN VERIFICAR SIDOF (DOF): los parámetros de consulta NO están documentados.
  EXCLUIDO      eleconomista.com.mx — responde 403 a clientes no-navegador. No
                se incluye: rotar User-Agents para saltarse un bloqueo explícito
                es pedir un bloqueo por IP y meter al repo en una pelea que no
                necesita.

urllib no descomprime solo. Arc XP manda gzip aunque no lo pidas, así que
`_get_bytes` revisa el header Y los magic bytes: hay servidores que comprimen
sin anunciarlo y un XML gzippeado parseado en crudo truena con un error que no
dice nada.
"""
from __future__ import annotations

import gzip
import json
import random
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from .market_stress import USER_AGENT

GDELT_DOC = "https://api.gdeltproject.org/api/v2/doc/doc"
SIDOF_JSON = "https://sidof.segob.gob.mx/datos_abiertos/getJSON/65"

RSS_FEEDS: dict[str, str] = {
    "expansion": "https://expansion.mx/rss",
    "el_financiero": "https://www.elfinanciero.com.mx/arc/outboundfeeds/rss/?outputType=xml",
    "bloomberg_linea": "https://www.bloomberglinea.com/arc/outboundfeeds/rss/?outputType=xml",
}

# Reintentos para GDELT. No son un parámetro ajustable: son el mínimo para
# sobrevivir a un 429 aislado sin convertirse en el motivo del siguiente 429.
MAX_INTENTOS = 3
BACKOFF_BASE_S = 1.5
CODIGOS_REINTENTABLES = (429, 500, 502, 503, 504)

# Umbral de anomalía de volumen. Es un juicio, no un dato: 2 desviaciones sobre
# la media móvil de la propia serie. Vive nombrado y aquí arriba por la misma
# razón que los umbrales de regime.py.
Z_ANOMALO = 2.0
MIN_PUNTOS_BASELINE = 10


# ---------------------------------------------------------------------------
# Lista curada de rupturas estructurales.
#
# ASIMETRÍA QUE JUSTIFICA CÓMO ESTÁ SINTONIZADA: un falso positivo cuesta UNA
# revisión manual de diez minutos. Un falso negativo cuesta la validez del
# modelo completo — seguir dimensionando una posición bajo un régimen fiscal o
# regulatorio que ya cambió, y enterarse por el saldo. Los costos no son
# comparables, así que la lista está deliberadamente sintonizada para
# SOBRE-DISPARAR. Si te cansa revisarla, la respuesta correcta es leer los
# artículos, no aflojar los patrones.
#
# Forma: (etiqueta, grupos). Un patrón coincide si CADA grupo aporta al menos
# un término presente en el texto (AND de ORs). Los grupos evitan que "cripto"
# a secas dispare todos los días, sin exigir una frase exacta que un cambio de
# redacción del periodista rompería.
# ---------------------------------------------------------------------------
Patron = tuple[str, tuple[tuple[str, ...], ...]]

PATRONES_RUPTURA: tuple[Patron, ...] = (
    (
        "CNBV cambia el estatus de activos virtuales o de una plataforma",
        (
            ("cnbv", "comision nacional bancaria", "comision nacional bancaria y de valores"),
            (
                "activo virtual", "activos virtuales", "criptomoneda", "criptomonedas",
                "cripto", "bitcoin", "binance", "bitso", "ley fintech",
                "institucion de tecnologia financiera", "itf", "plataforma de fondeo",
            ),
        ),
    ),
    (
        "SAT publica criterio o regla sobre activos virtuales",
        (
            ("sat", "servicio de administracion tributaria", "resolucion miscelanea",
             "miscelanea fiscal", "criterio normativo", "criterio no vinculativo"),
            ("activo virtual", "activos virtuales", "criptomoneda", "criptomonedas",
             "cripto", "bitcoin", "enajenacion de bienes muebles"),
        ),
    ),
    (
        "Banxico cambia el régimen cambiario o de operación en divisas",
        (
            ("banxico", "banco de mexico"),
            ("regimen cambiario", "tipo de cambio fijo", "control de cambios",
             "flotacion", "comision de cambios", "banda cambiaria",
             "intervencion cambiaria", "activo virtual", "activos virtuales"),
        ),
    ),
    (
        "LIF cambia la tasa de retención sobre intereses",
        (
            ("ley de ingresos", "lif", "paquete economico", "miscelanea fiscal"),
            ("retencion", "tasa de retencion", "intereses", "instrumentos de deuda",
             "rendimiento de capitales"),
        ),
    ),
    (
        "Cambio a LISR art. 93 (exención por enajenación de bienes muebles)",
        (
            ("lisr", "ley del impuesto sobre la renta", "impuesto sobre la renta",
             "reforma fiscal"),
            ("articulo 93", "art. 93", "exencion", "bienes muebles", "uma"),
        ),
    ),
    (
        "Cambio a LISR art. 134 (ISR sobre interés real)",
        (
            ("lisr", "ley del impuesto sobre la renta", "impuesto sobre la renta",
             "reforma fiscal"),
            ("articulo 134", "art. 134", "interes real", "ajuste por inflacion"),
        ),
    ),
    (
        "Prohibición, suspensión o licenciamiento forzoso de plataformas cripto",
        (
            ("prohibe", "prohibicion", "suspende", "suspension", "veta", "bloquea",
             "revoca", "licencia", "autorizacion"),
            ("activo virtual", "activos virtuales", "criptomoneda", "criptomonedas",
             "exchange de cripto", "binance", "bitso"),
        ),
    ),
)


class NewsError(RuntimeError):
    pass


class NewsUnavailable(NewsError):
    """
    La fuente no respondió o no es interpretable.

    NO DISPONIBLE ≠ TRANQUILO. Todo el módulo depende de que esta distinción se
    respete aguas abajo: `signals.combinar` trata una fuente caída como una
    razón para tener MENOS posición, nunca como permiso para tener más.
    """


@dataclass(frozen=True)
class Nota:
    fuente: str
    titulo: str
    resumen: str
    url: str
    fecha: date | None


@dataclass(frozen=True)
class VolumenAnomalo:
    disponible: bool
    anomalo: bool
    z: float | None
    valor_actual: float | None
    baseline_media: float | None
    baseline_desv: float | None
    n_baseline: int
    as_of: date | None
    nota: str


@dataclass(frozen=True)
class Coincidencia:
    etiqueta: str
    fuente: str
    titulo: str
    url: str
    fecha: date | None
    terminos: tuple[str, ...]


@dataclass(frozen=True)
class RupturaEstructural:
    disponible: bool
    detectada: bool
    coincidencias: tuple[Coincidencia, ...] = ()
    fuentes_revisadas: tuple[str, ...] = ()
    notas_revisadas: int = 0
    nota: str = ""


# ------------------------------------------------------------------- HTTP base

def _get_bytes(url: str, timeout: int = 20, intentos: int = 1) -> bytes:
    """
    GET crudo con descompresión defensiva y backoff exponencial opcional.

    El backoff tiene jitter porque el cron corre a la misma hora todos los
    días: sin jitter, cada reintento cae en el mismo segundo del minuto y el
    rate limiter del otro lado ve un patrón, no un cliente.
    """
    ultimo: Exception | None = None
    realizados = 0
    for intento in range(max(intentos, 1)):
        if intento:
            time.sleep(BACKOFF_BASE_S * (2 ** (intento - 1)) * (1.0 + random.random() * 0.3))
        realizados = intento + 1
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json, application/xml, text/xml, */*",
                "Accept-Encoding": "gzip, deflate",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return _descomprimir(r.read(), r.headers.get("Content-Encoding", ""))
        except urllib.error.HTTPError as e:
            ultimo = NewsUnavailable(f"HTTP {e.code} en {url}")
            if e.code not in CODIGOS_REINTENTABLES:
                break
        except Exception as e:  # noqa: BLE001
            ultimo = NewsUnavailable(f"Fallo de red en {url}: {e}")
    raise NewsUnavailable(f"{url} no disponible tras {realizados} intento(s): {ultimo}")


def _descomprimir(raw: bytes, content_encoding: str) -> bytes:
    """
    Arc XP responde gzip aunque no lo pidas y urllib no descomprime solo.
    Se revisan header Y magic bytes: hay servidores que comprimen sin anunciarlo.
    """
    enc = (content_encoding or "").lower()
    if "gzip" in enc or raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)
    if "deflate" in enc:
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS)  # deflate crudo, sin header
    return raw


def _normaliza(texto: str) -> str:
    """Minúsculas sin acentos. 'Comisión' y 'comision' son el mismo evento."""
    desc = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in desc if not unicodedata.combining(c)).lower()


# ------------------------------------------------------------------------ RSS

def _local(tag: object) -> str:
    """
    Nombre de etiqueta sin namespace: '{http://...}item' → 'item'.

    Todo el parseo se hace por nombre local a propósito. RSS 2.0 canónico no
    lleva namespace, pero un CMS puede publicar el mismo feed con uno por
    defecto de un día para otro, y `root.iter("item")` dejaría de encontrar
    nada — silenciosamente, con el feed entero contando como 0 notas, que es
    justo el falso negativo que este módulo existe para evitar.
    """
    t = tag if isinstance(tag, str) else ""
    return t.rsplit("}", 1)[-1].lower()


def _texto_hijo(el: ET.Element, *nombres: str) -> str:
    for hijo in el:
        if _local(hijo.tag) in nombres:
            return (hijo.text or "").strip()
    return ""


def parse_rss(raw: bytes, fuente: str) -> list[Nota]:
    """
    Parseo de RSS 2.0 con xml.etree. Sin feedparser: una dependencia de runtime
    para leer siete etiquetas no se justifica (CLAUDE.md, sección Estilo).

    Se le pasan BYTES, no str, para que ElementTree respete la declaración de
    encoding del prólogo XML en vez de que la adivinemos nosotros.
    """
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise NewsUnavailable(f"{fuente}: XML no parseable ({e}).") from e

    notas: list[Nota] = []
    for el in root.iter():
        nombre = _local(el.tag)
        if nombre == "item":  # RSS 2.0
            notas.append(
                Nota(
                    fuente=fuente,
                    titulo=_texto_hijo(el, "title"),
                    resumen=_texto_hijo(el, "description", "summary"),
                    url=_texto_hijo(el, "link", "guid"),
                    fecha=_parse_fecha_rss(_texto_hijo(el, "pubdate", "date", "published")),
                )
            )
        elif nombre == "entry":  # Atom, el plan B de algunos feeds Arc XP
            href = ""
            for hijo in el:
                if _local(hijo.tag) == "link":
                    href = hijo.get("href", "") or (hijo.text or "")
                    break
            notas.append(
                Nota(
                    fuente=fuente,
                    titulo=_texto_hijo(el, "title"),
                    resumen=_texto_hijo(el, "summary", "content"),
                    url=href.strip(),
                    fecha=_parse_fecha_rss(_texto_hijo(el, "updated", "published")),
                )
            )

    if not notas:
        raise NewsUnavailable(f"{fuente}: el feed parseó pero no trae <item> ni <entry>.")
    return notas


def _parse_fecha_rss(valor: str | None) -> date | None:
    """
    pubDate viene en RFC 822. Una fecha ilegible NO invalida la nota: el título
    sigue sirviendo para detectar una ruptura estructural, y perder la nota por
    un formato de fecha raro sería exactamente el falso negativo que este
    módulo existe para evitar.
    """
    if not valor:
        return None
    try:
        return parsedate_to_datetime(valor.strip()).astimezone(timezone.utc).date()
    except (TypeError, ValueError, IndexError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(valor.strip(), fmt).date()
        except ValueError:
            continue
    return None


def fetch_rss(fuente: str, timeout: int = 20) -> list[Nota]:
    if fuente not in RSS_FEEDS:
        raise ValueError(f"Feed desconocido: {fuente}. Conocidos: {sorted(RSS_FEEDS)}")
    return parse_rss(_get_bytes(RSS_FEEDS[fuente], timeout=timeout, intentos=2), fuente)


def fetch_todos_los_rss(timeout: int = 20) -> tuple[list[Nota], list[str]]:
    """Devuelve (notas, fuentes_no_disponibles). Ver `market_stress.recolectar`."""
    notas: list[Nota] = []
    caidas: list[str] = []
    for fuente in RSS_FEEDS:
        try:
            notas.extend(fetch_rss(fuente, timeout=timeout))
        except (NewsError, ValueError) as e:
            caidas.append(f"rss:{fuente}: {e}")
    return notas, caidas


# ---------------------------------------------------------------------- GDELT

def fetch_gdelt_timeline(
    consulta: str, timespan: str = "7d", timeout: int = 20
) -> list[tuple[date, float]]:
    """
    GDELT DOC 2.0, modo TimelineVol: % de cobertura mundial que coincide con la
    consulta, por intervalo. Es un VOLUMEN relativo, no un sentimiento.

    Estrangula agresivo (429 y luego 500 en la prueba en vivo de hoy), por eso
    User-Agent explícito y backoff. Si aun así falla, el llamador recibe una
    excepción y la traduce a "no disponible" — nunca a "sin anomalía".
    """
    qs = urllib.parse.urlencode(
        {"query": consulta, "mode": "TimelineVol", "format": "json", "timespan": timespan}
    )
    raw = _get_bytes(f"{GDELT_DOC}?{qs}", timeout=timeout, intentos=MAX_INTENTOS)
    return parse_gdelt_timeline(raw)


def parse_gdelt_timeline(raw: bytes) -> list[tuple[date, float]]:
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise NewsUnavailable(f"GDELT devolvió algo que no es JSON: {raw[:120]!r}") from e

    series = (payload or {}).get("timeline") or []
    if not isinstance(series, list) or not series:
        raise NewsUnavailable("GDELT devolvió 'timeline' vacío.")
    puntos = (series[0] or {}).get("data") or []

    out: list[tuple[date, float]] = []
    for p in puntos:
        if not isinstance(p, dict):
            continue
        try:
            # Formato verificado: 'YYYYMMDDTHHMMSSZ'.
            fecha = datetime.strptime(str(p["date"])[:8], "%Y%m%d").date()
            out.append((fecha, float(p["value"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not out:
        raise NewsUnavailable("GDELT: 'timeline[0].data' sin puntos parseables.")
    return out


# --------------------------------------------------------- (a) volumen anómalo

def volumen_anomalo(
    serie: Sequence[tuple[date, float]] | None,
    z_umbral: float = Z_ANOMALO,
    min_baseline: int = MIN_PUNTOS_BASELINE,
) -> VolumenAnomalo:
    """
    ¿El último punto está estadísticamente elevado contra su PROPIA línea base?

    Función pura: la red vive en `fetch_volumen_anomalo`. Así el umbral se
    puede probar sin tocar internet, que es lo que pide CLAUDE.md.

    `serie=None` significa "la fuente no respondió", y eso NO es lo mismo que
    "sin anomalía": devuelve disponible=False, y quien la consuma debe recortar
    tamaño por incertidumbre, no seguir como si nada.

    La desviación se calcula sobre TODO menos el último punto: incluir el punto
    que estás probando infla la desviación justo cuando hay un pico, que es
    precisamente cuando querías detectarlo.
    """
    if serie is None:
        return VolumenAnomalo(
            False, False, None, None, None, None, 0, None,
            "Volumen de noticias no disponible. Ausencia de dato ≠ ausencia de estrés.",
        )

    puntos = [(f, float(v)) for f, v in serie if v == v]  # v == v descarta NaN
    if len(puntos) < min_baseline + 1:
        return VolumenAnomalo(
            False, False, None, None, None, None, max(len(puntos) - 1, 0), None,
            f"Serie de {len(puntos)} puntos; se requieren {min_baseline + 1} para una"
            " línea base creíble. Sin señal.",
        )

    fecha_actual, actual = puntos[-1]
    base = [v for _, v in puntos[:-1]]
    n = len(base)
    media = sum(base) / n
    var = sum((v - media) ** 2 for v in base) / (n - 1)
    desv = var ** 0.5

    if desv <= 0:
        return VolumenAnomalo(
            False, False, None, actual, media, desv, n, fecha_actual,
            "Línea base con desviación cero (serie constante o degenerada). Sin señal.",
        )

    z = (actual - media) / desv
    anomalo = z >= z_umbral
    return VolumenAnomalo(
        True, anomalo, z, actual, media, desv, n, fecha_actual,
        f"Volumen {actual:.4f} vs línea base {media:.4f} ± {desv:.4f} (n={n}):"
        f" z = {z:+.2f}, umbral {z_umbral:.2f}."
        + (" ANÓMALO: corrobora estrés, no lo origina." if anomalo else " Dentro de rango."),
    )


def fetch_volumen_anomalo(
    consulta: str, timespan: str = "7d", z_umbral: float = Z_ANOMALO
) -> VolumenAnomalo:
    """Envoltura con red. Cualquier fallo se traduce a `disponible=False`."""
    try:
        serie = fetch_gdelt_timeline(consulta, timespan=timespan)
    except (NewsError, ValueError) as e:
        return VolumenAnomalo(
            False, False, None, None, None, None, 0, None,
            f"GDELT no disponible ({e}). Se trata como AUSENCIA DE DATO, nunca como calma.",
        )
    return volumen_anomalo(serie, z_umbral=z_umbral)


# ---------------------------------------------------- (b) ruptura estructural

def _coincide(patron: Patron, texto: str) -> tuple[str, ...] | None:
    """Devuelve los términos que dispararon, o None. AND de ORs; ver PATRONES_RUPTURA."""
    _, grupos = patron
    hits: list[str] = []
    for grupo in grupos:
        encontrado = next((t for t in grupo if t in texto), None)
        if encontrado is None:
            return None
        hits.append(encontrado)
    return tuple(hits)


def ruptura_estructural(
    notas: Sequence[Nota] | None,
    patrones: Sequence[Patron] = PATRONES_RUPTURA,
    desde: date | None = None,
) -> RupturaEstructural:
    """
    Busca eventos que INVALIDAN el modelo, no eventos que mueven el precio.

    Función pura sobre una lista de notas: los fetchers viven arriba. Una
    coincidencia levanta un bloqueo que exige revisión humana; el sistema no
    intenta interpretar la noticia, sólo se niega a seguir operando bajo
    supuestos que quizá ya no valen.
    """
    if notas is None:
        return RupturaEstructural(
            False, False, (), (), 0,
            "Sin feeds de noticias. No se puede descartar una ruptura regulatoria:"
            " la ausencia de la fuente no es evidencia de ausencia del evento.",
        )

    fuentes = tuple(sorted({n.fuente for n in notas}))
    hits: list[Coincidencia] = []
    for n in notas:
        if desde is not None and n.fecha is not None and n.fecha < desde:
            continue
        texto = _normaliza(f"{n.titulo} {n.resumen}")
        for patron in patrones:
            terminos = _coincide(patron, texto)
            if terminos:
                hits.append(
                    Coincidencia(patron[0], n.fuente, n.titulo, n.url, n.fecha, terminos)
                )

    if hits:
        etiquetas = sorted({h.etiqueta for h in hits})
        return RupturaEstructural(
            True, True, tuple(hits), fuentes, len(notas),
            f"{len(hits)} coincidencia(s) en {len(etiquetas)} categoría(s) de ruptura:"
            f" {'; '.join(etiquetas)}. REQUIERE REVISIÓN HUMANA antes de operar.",
        )
    return RupturaEstructural(
        True, False, (), fuentes, len(notas),
        f"{len(notas)} notas revisadas de {len(fuentes)} fuente(s); sin coincidencias"
        " con la lista curada de rupturas.",
    )


def fetch_ruptura_estructural(desde: date | None = None) -> tuple[RupturaEstructural, list[str]]:
    notas, caidas = fetch_todos_los_rss()
    dof, caida_dof = fetch_dof_notas()
    if caida_dof:
        caidas.append(caida_dof)
    notas.extend(dof)
    if not notas:
        return ruptura_estructural(None), caidas
    return ruptura_estructural(notas, desde=desde), caidas


# ------------------------------------------------------------- DOF vía SIDOF

# ⚠️ PARÁMETROS SIN VERIFICAR. `getJSON/65` (consulta diaria) responde, pero el
# esquema de sus query params NO está documentado en ningún lado público y no
# se pudo verificar en vivo. Los candidatos plausibles —fecha, anio/mes/dia,
# f_inicio/f_fin— son CONJETURA. Este fetcher se escribe defensivo a propósito:
# ante cualquier duda devuelve "no disponible" en vez de adivinar y publicar un
# resultado que parece un dato del DOF sin serlo (CLAUDE.md regla 5).
#
# TAREA PENDIENTE, no bug: hay que hacerle ingeniería inversa a los parámetros
# capturando lo que manda el portal https://sidof.segob.gob.mx desde el
# inspector de red del navegador, y verificar el mapeo de campos contra una
# edición del DOF conocida. Hasta entonces el DOF cuenta como fuente caída, y
# como tal RECORTA tamaño en vez de ser ignorado en silencio.
_CAMPOS_TITULO = ("titulo", "nombre", "descripcion", "nota", "asunto", "encabezado")
_CAMPOS_URL = ("url", "link", "enlace", "archivo", "pdf")
_CAMPOS_FECHA = ("fecha", "fecha_publicacion", "fechaPublicacion", "fecha_dof")


def fetch_dof_notas(
    params: dict[str, Any] | None = None, timeout: int = 20
) -> tuple[list[Nota], str]:
    """
    Devuelve (notas, mensaje_de_caida). Si el mensaje no está vacío, la fuente
    cuenta como NO DISPONIBLE para el combinador.
    """
    url = SIDOF_JSON
    if params:
        url = f"{SIDOF_JSON}?{urllib.parse.urlencode(params)}"
    try:
        raw = _get_bytes(url, timeout=timeout, intentos=2)
    except NewsError as e:
        return [], f"dof:sidof: {e}"

    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return [], f"dof:sidof: respuesta no-JSON ({e})."

    filas = _dof_filas(payload)
    if filas is None:
        return [], (
            "dof:sidof: forma de respuesta no reconocida. Los query params de"
            " getJSON/65 siguen sin documentar; falta ingeniería inversa."
        )

    notas = [n for n in (_dof_nota(f) for f in filas) if n is not None]
    if not notas:
        return [], "dof:sidof: 0 registros interpretables en la respuesta."
    return notas, ""


def _dof_filas(payload: Any) -> list[dict] | None:
    """El envoltorio del JSON no está documentado: se prueban las formas obvias."""
    if isinstance(payload, list):
        return [f for f in payload if isinstance(f, dict)]
    if isinstance(payload, dict):
        for clave in ("datos", "data", "registros", "resultados", "items"):
            valor = payload.get(clave)
            if isinstance(valor, list):
                return [f for f in valor if isinstance(f, dict)]
    return None


def _dof_nota(fila: dict) -> Nota | None:
    titulo = next((str(fila[c]) for c in _CAMPOS_TITULO if fila.get(c)), "")
    if not titulo.strip():
        return None
    url = next((str(fila[c]) for c in _CAMPOS_URL if fila.get(c)), "")
    fecha_raw = next((str(fila[c]) for c in _CAMPOS_FECHA if fila.get(c)), "")
    fecha = None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y"):
        try:
            fecha = datetime.strptime(fecha_raw.strip()[:19], fmt).date()
            break
        except ValueError:
            continue
    return Nota("dof", titulo.strip(), "", url.strip(), fecha)
