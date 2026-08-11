"""
Tests offline de estrés, noticias, calendario y combinador. Cero red.

Lo que se prueba aquí no es "las señales funcionan" — eso no se prueba con
tests. Lo que se prueba es la invariante que hace que este subsistema no sea
peligroso:

  - El multiplicador de señales SIEMPRE cae en [0.0, 1.0], con cualquier
    entrada, incluida basura adversarial. Nunca amplifica. Nunca truena.
  - Una fuente caída RECORTA tamaño. Jamás se lee como calma.
  - Una ruptura regulatoria levanta un BLOQUEO, no una advertencia en gris.
  - La tabla de escenarios de Banxico es internamente consistente.
  - Cuando el calendario duro se acaba, avisa en vez de inventar fechas.

Los fetchers no se prueban contra la red (CLAUDE.md: "pytest sin red"). Lo que
se prueba de ellos es el PARSEO, con payloads capturados de la forma real que
devuelven, porque ahí es donde viven los bugs: un arreglo que se vuelve objeto,
un gzip sin anunciar, un "." de FRED interpretado como cero.
"""
from __future__ import annotations

import gzip
import json
import math
import random
from datetime import date

import pytest

from inversor.config import Policy, Portfolio, RiskPolicy, TaxPolicy
from inversor.events import (
    BANXICO_2026,
    BANXICO_COBERTURA_HASTA,
    CPI_US_COBERTURA_HASTA,
    FOMC_COBERTURA_HASTA,
    cobertura_calendario,
    escenarios_banxico,
    proximos_eventos,
)
from inversor.signals import (
    FUENTES_CAIDAS_QUE_RECORTAN,
    MULT_MAXIMO,
    SignalState,
    combinar,
)
from inversor.sources import market_stress as ms
from inversor.sources import news as nw
from inversor.tax import hurdle_rate

HOY = date(2026, 8, 10)


# --------------------------------------------------------------- fixtures

def lectura(key: str, value: float, stale_days: int = 1, label: str = "") -> ms.StressReading:
    return ms.StressReading(
        key=key,
        source="fixture",
        series_id="TEST",
        value=value,
        as_of=HOY,
        stale_days=stale_days,
        label=label,
    )


def volumen(anomalo: bool = False, z: float = 0.3) -> nw.VolumenAnomalo:
    return nw.VolumenAnomalo(
        disponible=True, anomalo=anomalo, z=z, valor_actual=1.0,
        baseline_media=1.0, baseline_desv=0.1, n_baseline=20, as_of=HOY, nota="fixture",
    )


def sin_ruptura(n: int = 40) -> nw.RupturaEstructural:
    return nw.RupturaEstructural(True, False, (), ("expansion",), n, "fixture")


def con_ruptura() -> nw.RupturaEstructural:
    c = nw.Coincidencia(
        etiqueta="CNBV cambia el estatus de activos virtuales o de una plataforma",
        fuente="expansion", titulo="La CNBV suspende operaciones con activos virtuales",
        url="https://example.invalid/x", fecha=HOY, terminos=("cnbv", "activos virtuales"),
    )
    return nw.RupturaEstructural(True, True, (c,), ("expansion",), 40, "fixture")


def todo_en_calma(**over):
    base = dict(
        fear_greed=lectura("fear_greed", 62.0, label="Greed"),
        dvol=lectura("dvol_btc", 45.0),
        vix=lectura("vix", 15.0),
        volumen=volumen(),
        ruptura=sin_ruptura(),
        hoy=HOY,
    )
    base.update(over)
    return base


RSS_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Expansion</title><language>es-mx</language>
  <item>
    <title>La CNBV suspende operaciones con activos virtuales en ITF</title>
    <link>https://expansion.mx/n/1</link>
    <description>El regulador informo la suspension.</description>
    <pubDate>Mon, 10 Aug 2026 12:00:00 -0600</pubDate>
  </item>
  <item>
    <title>Bitcoin cae 12% en la sesion</title>
    <link>https://expansion.mx/n/2</link>
    <description>El mercado de criptomonedas retrocede.</description>
    <pubDate>Mon, 10 Aug 2026 09:00:00 -0600</pubDate>
  </item>
</channel></rss>"""

ATOM_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Nota en Atom</title>
    <link href="https://ejemplo.invalid/a"/>
    <summary>Resumen</summary>
    <updated>2026-08-10T12:00:00Z</updated>
  </entry>
</feed>"""


# =====================================================================
# LA INVARIANTE: el multiplicador vive en [0, 1] pase lo que pase
# =====================================================================

ADVERSARIALES = (
    None, 0, 1, -1, -0.0, 100, 101, -999, 1e308, -1e308,
    float("nan"), float("inf"), float("-inf"),
    10 ** 400,                      # int que no cabe en float: OverflowError
    "", "  ", "abc", "42", b"42",
    [], {}, (), set(), object(), True, False,
    complex(1, 2),
)


class _Basura:
    """Objeto con la forma de un StressReading pero con contenido adversarial."""

    def __init__(self, value, stale_days):
        self.value = value
        self.stale_days = stale_days


class _BasuraVolumen:
    def __init__(self, disponible, anomalo, z):
        self.disponible = disponible
        self.anomalo = anomalo
        self.z = z


class _BasuraRuptura:
    def __init__(self, disponible, detectada, coincidencias):
        self.disponible = disponible
        self.detectada = detectada
        self.coincidencias = coincidencias


def test_propiedad_multiplicador_siempre_en_cero_uno_y_nunca_truena():
    """
    El test que justifica la existencia del módulo.

    Cualquier combinación de entradas —None, NaN, negativos, infinitos, strings,
    listas vacías, enteros que no caben en un float, objetos sin los atributos
    esperados— debe producir un multiplicador en [0, 1] sin levantar excepción.
    Un crash aquí no es "un bug feo": el cron diario dejaría de publicar
    snapshot, y peor, un valor > 1.0 sería el sistema comprando por noticias,
    que es exactamente lo que este diseño existe para hacer imposible.
    """
    rng = random.Random(20260810)
    casos = 0

    # 1. Todas las entradas adversariales, una a la vez, en cada ranura.
    for v in ADVERSARIALES:
        for ranura in ("fear_greed", "dvol", "vix"):
            st = combinar(**{ranura: _Basura(v, 1)}, hoy=HOY)
            assert 0.0 <= st.multiplicador <= MULT_MAXIMO
            casos += 1
        for v2 in (None, float("nan"), -5, "x"):
            st = combinar(fear_greed=_Basura(v, v2), hoy=HOY)
            assert 0.0 <= st.multiplicador <= MULT_MAXIMO
            casos += 1

    # 2. Combinaciones aleatorias de basura en todas las ranuras a la vez.
    for _ in range(600):
        st = combinar(
            fear_greed=rng.choice(
                [None, _Basura(rng.choice(ADVERSARIALES), rng.choice([0, 1, 99, None]))]
            ),
            dvol=rng.choice(
                [None, _Basura(rng.choice(ADVERSARIALES), rng.choice([0, 1, -3, "z"]))]
            ),
            vix=rng.choice(
                [None, _Basura(rng.choice(ADVERSARIALES), rng.choice([0, 400, None]))]
            ),
            volumen=rng.choice([
                None,
                _BasuraVolumen(rng.choice([True, False, None, "si"]), rng.choice(ADVERSARIALES),
                               rng.choice(ADVERSARIALES)),
            ]),
            ruptura=rng.choice([
                None,
                _BasuraRuptura(rng.choice([True, False, 1, None]), rng.choice([True, False, 0]),
                               rng.choice([(), None, 5, "abc", [object()]])),
            ]),
            fuentes_no_disponibles=rng.choice([(), None, 7, "una", ["a", "b"], {"k": 1}]),
            hoy=HOY,
            max_staleness_days=rng.choice([None, 0, 5, -1]),
        )
        assert 0.0 <= st.multiplicador <= MULT_MAXIMO
        assert isinstance(st.blockers, list)
        assert isinstance(st.razones, list)
        assert isinstance(st.fuentes_no_disponibles, list)
        casos += 1

    # 3. Sin argumentos: el estado "no sé nada" tampoco puede salirse de rango.
    assert 0.0 <= combinar().multiplicador <= MULT_MAXIMO
    assert casos > 700


def test_signalstate_clampea_aunque_lo_construyas_a_mano():
    """La garantía no depende de pasar por combinar(). Vive en el tipo."""
    assert SignalState(multiplicador=7.0).multiplicador == 1.0
    assert SignalState(multiplicador=-3.0).multiplicador == 0.0
    assert SignalState(multiplicador=float("nan")).multiplicador == 0.0
    assert SignalState(multiplicador=float("inf")).multiplicador == 1.0
    assert SignalState(multiplicador="1.5").multiplicador == 1.0  # type: ignore[arg-type]
    assert SignalState(multiplicador=None).multiplicador == 0.0  # type: ignore[arg-type]


def test_aplicar_nunca_amplifica_el_multiplicador_de_regimen():
    for base in (0.0, 0.25, 0.6, 1.0, 3.0, -1.0, float("nan")):
        for m in (0.0, 0.4, 1.0, 5.0):
            r = SignalState(multiplicador=m).aplicar(base)
            assert 0.0 <= r <= 1.0
            assert r <= max(min(base if base == base else 0.0, 1.0), 0.0) + 1e-12


def test_ninguna_lectura_puede_aumentar_tamano():
    """Miedo recorta; codicia NO amplifica. Ese es todo el diseño."""
    calma = combinar(**todo_en_calma()).multiplicador
    assert calma == pytest.approx(1.0)

    codicia_extrema = combinar(**todo_en_calma(
        fear_greed=lectura("fear_greed", 95.0, label="Extreme Greed"),
        dvol=lectura("dvol_btc", 20.0),
        vix=lectura("vix", 9.0),
    )).multiplicador
    assert codicia_extrema == pytest.approx(1.0)
    assert codicia_extrema <= calma  # nunca por encima

    miedo_extremo = combinar(**todo_en_calma(
        fear_greed=lectura("fear_greed", 8.0, label="Extreme Fear")
    )).multiplicador
    assert miedo_extremo < calma


def test_dvol_y_vix_elevados_recortan():
    base = combinar(**todo_en_calma()).multiplicador
    assert combinar(**todo_en_calma(dvol=lectura("dvol_btc", 95.0))).multiplicador < base
    assert combinar(**todo_en_calma(vix=lectura("vix", 40.0))).multiplicador < base


def test_volumen_anomalo_recorta_pero_no_bloquea():
    st = combinar(**todo_en_calma(volumen=volumen(anomalo=True, z=3.4)))
    assert st.multiplicador < 1.0
    assert st.blockers == []
    assert any("z = +3.40" in r for r in st.razones)


# =====================================================================
# Fuentes caídas: recortan, nunca se leen como calma
# =====================================================================

def test_fuentes_no_disponibles_reducen_en_vez_de_aumentar():
    """
    Regla 4 llevada a las señales: la ausencia de dato no puede pagarse con la
    misma posición. Dos o más fuentes ciegas recortan.
    """
    completo = combinar(**todo_en_calma()).multiplicador
    assert completo == pytest.approx(1.0)

    st = combinar(fear_greed=None, dvol=None, vix=lectura("vix", 15.0),
                  volumen=volumen(), ruptura=sin_ruptura(), hoy=HOY)
    assert len(st.fuentes_no_disponibles) >= FUENTES_CAIDAS_QUE_RECORTAN
    assert st.multiplicador < completo
    assert st.multiplicador <= MULT_MAXIMO
    assert any("no disponibles" in r for r in st.razones)


def test_todas_las_fuentes_caidas_no_es_calma():
    st = combinar(hoy=HOY)
    assert st.multiplicador < 1.0
    assert len(st.fuentes_no_disponibles) >= 4


def test_dato_rancio_cuenta_como_no_disponible_no_como_lectura():
    """Nunca se usa el último valor conocido en silencio (CLAUDE.md regla 4)."""
    st = combinar(**todo_en_calma(
        fear_greed=lectura("fear_greed", 12.0, stale_days=40),
        dvol=lectura("dvol_btc", 45.0, stale_days=40),
    ))
    assert any("rancio" in f for f in st.fuentes_no_disponibles)
    assert st.multiplicador < 1.0
    # Y no se coló la lectura de miedo extremo como si fuera fresca:
    assert not any("miedo extremo" in r.lower() for r in st.razones)


def test_fecha_en_el_futuro_se_rechaza():
    st = combinar(**todo_en_calma(vix=lectura("vix", 15.0, stale_days=-3)))
    assert any("futuro" in f for f in st.fuentes_no_disponibles)


def test_un_dia_negativo_es_huso_horario_no_dato_corrupto():
    """
    Los fetchers fechan en UTC y date.today() es local: desde México a las 19:00
    la barra de hoy ya está estampada mañana. Rechazarla convertiría cada tarde
    en 'fuente caída' y recortaría el sleeve por un problema de husos.
    """
    st = combinar(**todo_en_calma(vix=lectura("vix", 15.0, stale_days=-1)))
    assert st.fuentes_no_disponibles == []
    assert st.multiplicador == pytest.approx(1.0)


# =====================================================================
# Ruptura estructural: bloqueo, no advertencia
# =====================================================================

def test_ruptura_estructural_levanta_bloqueo():
    st = combinar(**todo_en_calma(ruptura=con_ruptura()))
    assert st.blockers
    assert any("RUPTURA ESTRUCTURAL" in b for b in st.blockers)
    assert any("revisión humana" in b for b in st.blockers)


def test_ruptura_detectada_sin_detalle_igual_bloquea():
    st = combinar(**todo_en_calma(ruptura=_BasuraRuptura(True, True, ())))
    assert st.blockers


def test_deteccion_de_ruptura_sobre_titulares_reales():
    notas = nw.parse_rss(RSS_FIXTURE, "expansion")
    r = nw.ruptura_estructural(notas)
    assert r.disponible is True
    assert r.detectada is True
    assert any("CNBV" in c.etiqueta for c in r.coincidencias)
    # "Bitcoin cae 12%" es movimiento de precio, no ruptura del modelo.
    assert all("cae 12%" not in c.titulo for c in r.coincidencias)


@pytest.mark.parametrize(
    "titulo",
    [
        "El SAT publica criterio normativo sobre activos virtuales",
        "Banxico anuncia cambios al régimen cambiario",
        "La Ley de Ingresos sube la tasa de retención sobre intereses",
        "Reforma fiscal modifica el artículo 93 de la LISR",
        "Reforma fiscal toca el artículo 134 y el interés real",
        "Comisión Nacional Bancaria y de Valores revoca licencia a Bitso",
    ],
)
def test_lista_curada_sobre_dispara_a_proposito(titulo):
    """Un falso positivo cuesta una revisión; un falso negativo cuesta el modelo."""
    n = nw.Nota("test", titulo, "", "", HOY)
    assert nw.ruptura_estructural([n]).detectada is True


def test_ruido_de_precio_no_dispara_ruptura():
    ruido = [
        nw.Nota("test", "Bitcoin sube 8% tras datos de empleo", "", "", HOY),
        nw.Nota("test", "El peso se aprecia frente al dólar", "", "", HOY),
        nw.Nota("test", "Wall Street cierra en verde", "", "", HOY),
    ]
    r = nw.ruptura_estructural(ruido)
    assert r.detectada is False
    assert r.disponible is True
    assert r.notas_revisadas == 3


def test_sin_feeds_no_es_lo_mismo_que_sin_ruptura():
    r = nw.ruptura_estructural(None)
    assert r.disponible is False
    assert r.detectada is False
    st = combinar(**todo_en_calma(ruptura=r))
    assert any("ruptura_estructural" in f for f in st.fuentes_no_disponibles)


# =====================================================================
# Volumen anómalo (función pura)
# =====================================================================

def _serie(valores):
    return [(date(2026, 7, 1 + i), v) for i, v in enumerate(valores)]


def test_volumen_anomalo_detecta_pico_contra_su_propia_base():
    serie = _serie([1.0, 1.1, 0.9, 1.05, 0.95, 1.0, 1.02, 0.98, 1.03, 0.97, 1.01, 5.0])
    v = nw.volumen_anomalo(serie)
    assert v.disponible is True
    assert v.anomalo is True
    assert v.z is not None and v.z > 2.0


def test_volumen_normal_no_dispara():
    serie = _serie([1.0, 1.1, 0.9, 1.05, 0.95, 1.0, 1.02, 0.98, 1.03, 0.97, 1.01, 1.04])
    v = nw.volumen_anomalo(serie)
    assert v.disponible is True and v.anomalo is False


def test_serie_corta_no_inventa_baseline():
    v = nw.volumen_anomalo(_serie([1.0, 2.0, 3.0]))
    assert v.disponible is False and v.anomalo is False


def test_serie_ausente_es_no_disponible_no_es_calma():
    v = nw.volumen_anomalo(None)
    assert v.disponible is False and v.anomalo is False
    assert "no disponible" in v.nota.lower()


def test_serie_constante_no_produce_z_infinito():
    v = nw.volumen_anomalo(_serie([2.0] * 12))
    assert v.disponible is False
    assert v.z is None


def test_desviacion_excluye_el_punto_que_se_esta_probando():
    """Incluirlo infla la desviación justo cuando hay pico y mata la detección."""
    serie = _serie([1.0] * 11 + [1.6])
    v = nw.volumen_anomalo(serie)
    assert v.n_baseline == 11
    assert v.baseline_media == pytest.approx(1.0)


# =====================================================================
# Parseo de fuentes (payloads con la forma real, sin red)
# =====================================================================

def test_rss_2_0_se_parsea_con_xml_etree():
    notas = nw.parse_rss(RSS_FIXTURE, "expansion")
    assert len(notas) == 2
    assert notas[0].fuente == "expansion"
    assert notas[0].fecha == date(2026, 8, 10)
    assert notas[0].url.startswith("https://")


def test_atom_es_el_plan_b_cuando_no_hay_item():
    notas = nw.parse_rss(ATOM_FIXTURE, "bloomberg_linea")
    assert len(notas) == 1 and notas[0].titulo == "Nota en Atom"


def test_rss_con_namespace_por_defecto_no_se_vuelve_invisible():
    """
    Si un CMS empieza a publicar el mismo feed con namespace, `iter("item")`
    devuelve 0 notas en silencio y el feed entero deja de vigilarse. Ese es un
    falso negativo perfecto: nada truena y nada se detecta.
    """
    con_ns = RSS_FIXTURE.replace(
        b'<rss version="2.0">', b'<rss version="2.0" xmlns="http://purl.org/rss/1.0/">'
    )
    notas = nw.parse_rss(con_ns, "expansion")
    assert len(notas) == 2
    assert nw.ruptura_estructural(notas).detectada is True


def test_xml_roto_no_se_interpreta_como_feed_vacio():
    with pytest.raises(nw.NewsUnavailable):
        nw.parse_rss(b"<rss><channel>", "expansion")


def test_gzip_anunciado_y_no_anunciado_se_descomprimen():
    """Arc XP responde gzip aunque no lo pidas; urllib no descomprime solo."""
    comprimido = gzip.compress(RSS_FIXTURE)
    assert nw._descomprimir(comprimido, "gzip") == RSS_FIXTURE
    assert nw._descomprimir(comprimido, "") == RSS_FIXTURE          # magic bytes
    assert nw._descomprimir(RSS_FIXTURE, "") == RSS_FIXTURE         # sin comprimir


def test_gdelt_timelinevol_se_parsea():
    payload = json.dumps({
        "timeline": [{
            "series": "Volume Intensity",
            "data": [
                {"date": "20260803T120000Z", "value": 0.0121},
                {"date": "20260804T120000Z", "value": 0.0133},
            ],
        }]
    }).encode()
    serie = nw.parse_gdelt_timeline(payload)
    assert serie[0] == (date(2026, 8, 3), pytest.approx(0.0121))


def test_gdelt_vacio_o_html_es_no_disponible_no_es_cero():
    with pytest.raises(nw.NewsUnavailable):
        nw.parse_gdelt_timeline(b"<html>429 Too Many Requests</html>")
    with pytest.raises(nw.NewsUnavailable):
        nw.parse_gdelt_timeline(json.dumps({"timeline": []}).encode())


def test_fear_and_greed_lee_strings_y_epoch(monkeypatch):
    payload = {"data": [{
        "value": "18",
        "value_classification": "Extreme Fear",
        "timestamp": "1786492800",
    }]}
    monkeypatch.setattr(ms, "_get_json", lambda url, timeout=20, redact="": payload)
    r = ms.fetch_fear_greed(today=date(2026, 8, 15))
    assert r.value == 18.0 and r.label == "Extreme Fear"
    assert r.as_of == date(2026, 8, 12)
    assert r.stale_days == 3


def test_fear_and_greed_fuera_de_rango_truena(monkeypatch):
    payload = {"data": [{"value": "1800", "value_classification": "?", "timestamp": "1786492800"}]}
    monkeypatch.setattr(ms, "_get_json", lambda url, timeout=20, redact="": payload)
    with pytest.raises(ms.StressError):
        ms.fetch_fear_greed(today=date(2026, 8, 15))


def test_dvol_lee_arreglos_no_objetos(monkeypatch):
    payload = {"result": {"data": [
        [1786406400000, 52.1, 53.0, 51.4, 52.6],
        [1786492800000, 52.6, 55.2, 52.0, 54.8],
    ]}}
    monkeypatch.setattr(ms, "_get_json", lambda url, timeout=20, redact="": payload)
    r = ms.fetch_dvol("BTC", today=date(2026, 8, 12))
    assert r.value == pytest.approx(54.8)      # el CIERRE, índice 4
    assert r.as_of == date(2026, 8, 12)


def test_dvol_con_forma_de_objeto_truena_en_vez_de_leer_basura():
    with pytest.raises(ms.StressError):
        ms._dvol_ultimo_cierre({"result": {"data": [{"close": 54.8}]}})


def test_dvol_solo_btc_y_eth():
    with pytest.raises(ValueError):
        ms.fetch_dvol("SOL")


def test_deribit_error_jsonrpc_es_no_disponible(monkeypatch):
    monkeypatch.setattr(
        ms, "_get_json",
        lambda url, timeout=20, redact="": {"error": {"code": 10001, "message": "bad"}},
    )
    with pytest.raises(ms.StressUnavailable):
        ms.fetch_dvol("BTC", today=HOY)


def test_fred_salta_los_huecos_marcados_con_punto(monkeypatch):
    payload = {"observations": [
        {"date": "2026-08-10", "value": "."},      # feriado / sin dato
        {"date": "2026-08-07", "value": "17.53"},
    ]}
    monkeypatch.setattr(ms, "_get_json", lambda url, timeout=20, redact="": payload)
    r = ms.fetch_fred("vix", api_key="k" * 32, today=date(2026, 8, 10))
    assert r.value == pytest.approx(17.53)
    assert r.as_of == date(2026, 8, 7) and r.stale_days == 3


def test_fred_sin_llave_degrada_no_truena_feo(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert ms.fred_api_key() is None
    with pytest.raises(ms.StressUnavailable) as e:
        ms.fetch_fred("vix", today=HOY)
    assert "FRED_API_KEY" in str(e.value)


def test_la_llave_de_fred_nunca_viaja_a_un_mensaje_de_error(monkeypatch):
    """El snapshot es público: una llave en un texto de error se publica sola."""
    visto = {}

    def fake(url, timeout=20, redact=""):
        visto["redact"] = redact
        raise ms.StressUnavailable(f"HTTP 400 en {url}".replace(redact, "***"))

    monkeypatch.setattr(ms, "_get_json", fake)
    with pytest.raises(ms.StressUnavailable) as e:
        ms.fetch_fred("vix", api_key="secreto" * 4, today=HOY)
    assert visto["redact"] == "secreto" * 4
    assert "secreto" not in str(e.value)


def test_serie_fred_desconocida_truena_en_vez_de_adivinar():
    with pytest.raises(ValueError):
        ms.fetch_fred("dxy_ice")     # no existe en FRED; ver docstring del módulo


def test_recolectar_reporta_lo_caido_en_vez_de_omitirlo(monkeypatch):
    def fng(today=None):
        return lectura("fear_greed", 55.0)

    def revienta(*a, **k):
        raise ms.StressUnavailable("simulado: sin red")

    monkeypatch.setattr(ms, "fetch_fear_greed", fng)
    monkeypatch.setattr(ms, "fetch_dvol", revienta)
    monkeypatch.setattr(ms, "fetch_fred", revienta)
    lecturas, caidas = ms.recolectar(("fear_greed", "dvol_btc", "vix"), today=HOY)
    assert set(lecturas) == {"fear_greed"}
    assert len(caidas) == 2


def test_recolectar_trata_lo_rancio_como_caido(monkeypatch):
    monkeypatch.setattr(
        ms, "fetch_fear_greed", lambda today=None: lectura("fear_greed", 55.0, stale_days=30)
    )
    lecturas, caidas = ms.recolectar(("fear_greed",), today=HOY)
    assert lecturas == {}
    assert caidas and "antigüedad" in caidas[0]


def test_dof_degrada_a_no_disponible_cuando_la_forma_no_se_reconoce(monkeypatch):
    """Una forma cambiada del servicio se lee como ceguera, nunca se adivina."""
    monkeypatch.setattr(nw, "_get_bytes", lambda *a, **k: b'{"algo":"raro"}')
    notas, caida = nw.fetch_dof_notas(hoy=HOY)
    assert notas == []
    assert "sidof" in caida


def _dof_fixture(nombre: str) -> bytes:
    from pathlib import Path

    return (Path(__file__).parent / "fixtures" / nombre).read_bytes()


def _dof_get_bytes_real(url: str, **_: object) -> bytes:
    # Respuestas REALES capturadas del servicio el 11-ago-2026.
    if "diarios/porFecha" in url:
        return _dof_fixture("dof_diarios_porfecha.json")
    if "obtenerNotasPorDiario" in url:
        return _dof_fixture("dof_notas_por_diario.json")
    raise AssertionError(f"URL inesperada: {url}")


def test_dof_parsea_el_flujo_documentado(monkeypatch):
    """diarios/porFecha → obtenerNotasPorDiario, con las respuestas reales."""
    monkeypatch.setattr(nw, "_get_bytes", _dof_get_bytes_real)
    notas, caida = nw.fetch_dof_notas(hoy=date(2026, 8, 11))
    assert caida == ""
    # El fixture trae 5 notas: 4 con título y 1 sin (nota de sólo imagen,
    # existe en el diario real). La sin título se salta, no truena.
    assert len(notas) == 4
    assert all(n.fuente == "dof" for n in notas)
    assert all(n.fecha == date(2026, 8, 11) for n in notas)
    assert any("Banco de Mexico".casefold() in n.resumen.casefold() for n in notas)
    assert all(n.url.startswith("https://sidof.segob.gob.mx/notas/") for n in notas)


def test_dof_dia_inhabil_no_es_ceguera(monkeypatch):
    """El DOF no publica sábados/domingos/feriados: [] sin caída — un hecho
    verificable, no ceguera. Un feriado no debe acercar el recorte 0.60x."""
    vacio = b'{"messageCode":200,"response":"OK","Matutina":null,"Vespertina":null,"Extraordinaria":null}'
    monkeypatch.setattr(nw, "_get_bytes", lambda *a, **k: vacio)
    notas, caida = nw.fetch_dof_notas(hoy=HOY)
    assert notas == [] and caida == ""


def test_dof_cae_al_host_de_respaldo(monkeypatch):
    intentos: list[str] = []

    def get_con_fallo(url, **k):
        intentos.append(url)
        if url.startswith(nw.SIDOF_HOSTS[0]):
            raise nw.NewsUnavailable("HTTP 503")
        return _dof_get_bytes_real(url)

    monkeypatch.setattr(nw, "_get_bytes", get_con_fallo)
    notas, caida = nw.fetch_dof_notas(hoy=HOY)
    assert caida == "" and len(notas) == 4
    assert any(u.startswith(nw.SIDOF_HOSTS[1]) for u in intentos)


def test_dof_organismo_alimenta_los_patrones_de_ruptura(monkeypatch):
    """El resumen lleva los organismos a propósito: 'COMISION NACIONAL
    BANCARIA Y DE VALORES' como emisor + 'activos virtuales' en el título es
    exactamente la ruptura que la lista curada debe atrapar."""
    payload = {
        "messageCode": 200, "response": "OK",
        "Notas": [{
            "codNota": 999, "fecha": "11-08-2026",
            "titulo": "Disposiciones de carácter general sobre activos virtuales",
            "nombreCodOrgaUno": "PODER EJECUTIVO",
            "codOrgaDos": "COMISION NACIONAL BANCARIA Y DE VALORES",
        }],
    }
    notas = nw._dof_notas_de_diario(payload)
    assert notas is not None and len(notas) == 1
    rup = nw.ruptura_estructural(notas)
    assert rup.detectada
    assert any("CNBV" in c.etiqueta for c in rup.coincidencias)


# =====================================================================
# Calendario de eventos
# =====================================================================

def test_proximos_eventos_incluye_banxico_fomc_y_cpi_dentro_de_cobertura():
    ev = proximos_eventos(date(2026, 9, 1), 30)
    tipos = {e.tipo for e in ev}
    assert {"BANXICO", "FOMC", "CPI_US", "SUBASTA_CETES", "INPC"} <= tipos
    assert "CALENDARIO_AGOTADO" not in tipos
    banxico = [e for e in ev if e.tipo == "BANXICO"]
    assert [e.fecha for e in banxico] == [date(2026, 9, 24)]
    assert banxico[0].verificado is False        # fecha derivada, no leída limpio


def test_eventos_ordenados_por_fecha():
    ev = proximos_eventos(date(2026, 9, 1), 60)
    assert [e.fecha for e in ev] == sorted(e.fecha for e in ev)


def test_subastas_cetes_se_generan_y_caen_en_martes():
    # Del martes 1-sep al martes 29-sep, ambos inclusive: cinco subastas.
    ev = [e for e in proximos_eventos(date(2026, 9, 1), 28) if e.tipo == "SUBASTA_CETES"]
    assert len(ev) == 5
    assert all(e.fecha.weekday() == 1 for e in ev)
    assert all("Colocación" in e.nota for e in ev)


def test_calendario_agotado_avisa_en_vez_de_inventar_fechas():
    """
    2027 de Banxico no está publicado. El código NO extrapola: emite un aviso.

    Devolver una lista vacía sería indistinguible de "no viene nada", y esa
    ambigüedad es la que hace que alguien opere el día de una decisión de tasa.
    """
    ev = proximos_eventos(date(2028, 3, 1), 60)
    tipos = {e.tipo for e in ev}
    assert "BANXICO" not in tipos and "FOMC" not in tipos and "CPI_US" not in tipos

    avisos = [e for e in ev if e.tipo == "CALENDARIO_AGOTADO"]
    assert {"BANXICO", "FOMC", "CPI_US"} <= {a.nombre.split()[1] for a in avisos}
    assert ev  # nunca una lista vacía silenciosa
    for a in avisos:
        assert a.fecha >= date(2028, 3, 1)     # no se inventa una fecha pasada
        assert "NO se extrapolan fechas" in a.nota


def test_cobertura_reporta_hasta_donde_llega_el_calendario_duro():
    completa, faltantes = cobertura_calendario(date(2026, 9, 1), 30)
    assert completa is True and faltantes == []
    completa, faltantes = cobertura_calendario(date(2028, 1, 1), 30)
    assert completa is False and len(faltantes) == 3


def test_las_fechas_duras_no_tienen_eventos_pasados_ni_desordenados():
    assert list(BANXICO_2026) == sorted(BANXICO_2026)
    assert all(f <= BANXICO_COBERTURA_HASTA for f in BANXICO_2026)
    assert FOMC_COBERTURA_HASTA.year == 2027
    assert CPI_US_COBERTURA_HASTA.year == 2026


def test_ventana_negativa_truena():
    with pytest.raises(ValueError):
        proximos_eventos(HOY, -1)


# =====================================================================
# Escenarios de Banxico
# =====================================================================

CURVA = {28: 0.0617, 91: 0.0640, 182: 0.0675, 364: 0.0701}


def _hurdle_base(p: Policy, inflacion: float = 0.0312) -> float:
    return hurdle_rate(CURVA[364], inflacion, p.tax, p.required_risk_premium)[0]


def test_tabla_de_escenarios_es_internamente_consistente():
    """
    Un recorte de tasa baja el hurdle y sube el sleeve objetivo; un alza hace
    lo contrario. Monótono en los cuatro escenarios, sin excepciones.
    """
    p = Policy()
    tabla = escenarios_banxico(_hurdle_base(p), CURVA, p, inflacion=0.0312)
    assert [e.movimiento_bp for e in tabla] == [-50, -25, 0, 25]

    hurdles = [e.hurdle_anualizado for e in tabla]
    sleeves = [e.sleeve_objetivo_mxn for e in tabla]
    assert hurdles == sorted(hurdles)                    # más tasa ⇒ más hurdle
    assert sleeves == sorted(sleeves, reverse=True)      # más tasa ⇒ menos sleeve

    recorte50 = tabla[0]
    base = tabla[2]
    assert recorte50.hurdle_anualizado < base.hurdle_anualizado
    assert recorte50.sleeve_objetivo_mxn > base.sleeve_objetivo_mxn
    assert recorte50.delta_hurdle_bp < 0 and recorte50.delta_sleeve_mxn > 0
    assert base.delta_hurdle_bp == pytest.approx(0.0)
    assert base.delta_sleeve_mxn == pytest.approx(0.0)


def test_el_desplazamiento_es_paralelo_y_se_declara_como_supuesto():
    p = Policy()
    tabla = escenarios_banxico(_hurdle_base(p), CURVA, p, inflacion=0.0312)
    alza = next(e for e in tabla if e.movimiento_bp == 25)
    assert alza.cetes_nominal == pytest.approx(CURVA[364] + 0.0025)
    assert any("PARALELO" in s for s in alza.supuestos)
    assert any("NO asigna probabilidades" in s for s in alza.supuestos)


def test_escenarios_usan_el_plazo_que_calza_el_horizonte():
    p = Policy(portfolio=Portfolio(total_capital_mxn=50_000, horizon_days=28))
    hurdle = hurdle_rate(CURVA[28], 0.0312, p.tax, p.required_risk_premium)[0]
    tabla = escenarios_banxico(hurdle, CURVA, p, inflacion=0.0312)
    assert all(e.tenor_days == 28 for e in tabla)
    assert all(e.hurdle_periodo < e.hurdle_anualizado / 10 for e in tabla)


def test_hurdle_del_periodo_en_vez_del_anualizado_truena():
    """El error más caro que tuvo este motor no puede volver por la puerta de atrás."""
    p = Policy()
    with pytest.raises(ValueError) as e:
        escenarios_banxico(0.0079, CURVA, p, inflacion=0.0312)  # hurdle de 28d
    assert "anualizado" in str(e.value)


def test_el_multiplicador_de_senales_solo_recorta_el_sleeve_del_escenario():
    p = Policy()
    h = _hurdle_base(p)
    completo = escenarios_banxico(h, CURVA, p, inflacion=0.0312, multiplicador=1.0)
    recortado = escenarios_banxico(h, CURVA, p, inflacion=0.0312, multiplicador=0.5)
    amplificado = escenarios_banxico(h, CURVA, p, inflacion=0.0312, multiplicador=4.0)
    for a, b, c in zip(completo, recortado, amplificado):
        assert b.sleeve_objetivo_mxn < a.sleeve_objetivo_mxn
        assert c.sleeve_objetivo_mxn == pytest.approx(a.sleeve_objetivo_mxn)


def test_el_sleeve_del_escenario_respeta_el_tope_duro_y_el_piso():
    p = Policy(risk=RiskPolicy(max_portfolio_drawdown_from_crypto=0.90,
                               max_crypto_weight=0.20, min_crypto_weight=0.03))
    tabla = escenarios_banxico(_hurdle_base(p), CURVA, p, inflacion=0.0312)
    assert all(e.peso_objetivo <= 0.20 + 1e-12 for e in tabla)
    assert all(e.restriccion == "hard_cap" for e in tabla)

    estricto = Policy(risk=RiskPolicy(max_portfolio_drawdown_from_crypto=0.005,
                                      min_crypto_weight=0.03))
    tabla = escenarios_banxico(_hurdle_base(estricto), CURVA, estricto, inflacion=0.0312)
    assert all(e.sleeve_objetivo_mxn == 0.0 for e in tabla)
    assert all(e.restriccion == "below_floor" for e in tabla)


def test_la_vol_realizada_entra_como_restriccion_cuando_se_conoce():
    p = Policy()
    h = _hurdle_base(p)
    sin_vol = escenarios_banxico(h, CURVA, p, inflacion=0.0312)
    con_vol = escenarios_banxico(h, CURVA, p, inflacion=0.0312, vol_annual=1.6)
    for a, b in zip(sin_vol, con_vol):
        assert b.sleeve_objetivo_mxn <= a.sleeve_objetivo_mxn
    assert any(e.restriccion == "vol_target" for e in con_vol)


def test_curva_vacia_truena():
    with pytest.raises(ValueError):
        escenarios_banxico(0.10, {}, Policy(), inflacion=0.0312)


def test_sin_escenario_de_referencia_truena():
    p = Policy()
    with pytest.raises(ValueError):
        escenarios_banxico(_hurdle_base(p), CURVA, p, inflacion=0.0312,
                           movimientos=((-25, "recorte"), (25, "alza")))


def test_isr_cero_no_cambia_la_direccion_de_la_tabla():
    """La monotonía no depende de la tarifa fiscal supuesta."""
    p = Policy(tax=TaxPolicy(marginal_isr_rate=0.0))
    tabla = escenarios_banxico(_hurdle_base(p), CURVA, p, inflacion=0.0312)
    assert [e.hurdle_anualizado for e in tabla] == sorted(e.hurdle_anualizado for e in tabla)
    assert tabla[0].sleeve_objetivo_mxn > tabla[-1].sleeve_objetivo_mxn


# =====================================================================
# Serialización (el snapshot es la interfaz con Android)
# =====================================================================

def test_signal_state_es_serializable():
    st = combinar(**todo_en_calma(ruptura=con_ruptura(), volumen=volumen(True, 3.1)))
    payload = json.dumps(st.to_json_dict(), ensure_ascii=False)
    assert "multiplicador" in payload
    assert math.isfinite(json.loads(payload)["multiplicador"])
