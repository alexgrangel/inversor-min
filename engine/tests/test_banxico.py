"""
Validación estructural de las series de Banxico. Cero red: los títulos son
fixtures capturados del catálogo oficial (GET /series/{id}) el 10-ago-2026.

SANITY atrapa basura numérica; estos tests prueban que la capa estructural
atrapa lo plausible-pero-equivocado:

  - Un título de inflación subyacente (o no subyacente) donde esperamos la
    general. Es el bug real que existió: SP74665 publicaba 0.29% "anual" y
    pasaba SANITY mientras la general estaba en 3.12%.
  - Un título de CETES con el plazo equivocado, o de la familia de promedio
    mensual en vez de la subasta primaria.
  - Una curva CETES que zigzaguea: plazos intercambiados o dato dislocado.
"""
from __future__ import annotations

from datetime import date

import pytest

from inversor.sources.banxico import (
    SERIES,
    BanxicoError,
    Observation,
    cetes_curve,
    validate_cetes_curve,
    validate_series_title,
)

# Títulos oficiales reales, capturados con `python -m inversor verify-series`
# el 10-ago-2026. Si Banxico renombra una serie, este fixture se actualiza
# corriendo verify-series de nuevo — no a mano.
TITULOS_OFICIALES = {
    "fix_usdmxn": (
        "Tipo de cambio                                          Pesos por dólar E.U.A."
        " Tipo de cambio para solventar obligaciones denominadas en moneda extranjera"
        " Fecha de determinación (FIX)"
    ),
    "udis": "Valor de UDIS",
    "cetes_28": (
        "Valores gubernamentales, Resultados de la subasta semanal Cetes a 28 días"
        " - Tasa de rendimiento - Fecha subasta"
    ),
    "cetes_91": (
        "Valores gubernamentales, Resultados de la subasta semanal Cetes a 91 días"
        " - Tasa de rendimiento - Fecha subasta"
    ),
    "cetes_182": (
        "Valores gubernamentales, Resultados de la subasta semanal Cetes a 182 días"
        " - Tasa de rendimiento - Fecha subasta"
    ),
    "cetes_364": (
        "Valores gubernamentales, Resultados de la subasta semanal Cetes a 364 días"
        " - Tasa de rendimiento - Fecha subasta"
    ),
    "tasa_objetivo": "Tasa objetivo",
    "inpc_anual": "Índice Nacional de Precios al consumidor variación anual",
}

# La subasta real del 4-ago-2026, en puntos porcentuales.
CURVA_REAL = {28: 6.17, 91: 6.40, 182: 6.75, 364: 7.01}


# ---------------- IDs ----------------


def test_ids_verificados_no_cambian_por_accidente():
    # Pin de regresión: estos IDs se confirmaron contra el título oficial del
    # catálogo el 10-ago-2026 (incluida la corrección SP74665 → SP30578). Sin
    # este pin, revertir inpc_anual a SP74665 pasaba los 191 tests: los
    # fixtures de título están indexados por llave lógica y "acompañan" a la
    # llave aunque el ID regrese al equivocado. Si cambias un ID a propósito,
    # corre verify-series y actualiza este test en el mismo commit.
    assert SERIES == {
        "fix_usdmxn": "SF43718",
        "udis": "SP68257",
        "cetes_28": "SF60633",
        "cetes_91": "SF60634",
        "cetes_182": "SF60635",
        "cetes_364": "SF60636",
        "tasa_objetivo": "SF61745",
        "inpc_anual": "SP30578",
    }


# ---------------- títulos ----------------


def test_titulos_oficiales_reales_pasan_todos():
    for key in SERIES:
        assert validate_series_title(key, TITULOS_OFICIALES[key]) == [], key


def test_toda_serie_tiene_patron_de_titulo_y_rango_sanity():
    # Una llave nueva sin patrón pasaría la validación con cualquier título;
    # una sin rango SANITY truena con KeyError crudo en fetch_latest, en
    # runtime y con red, en vez de aquí.
    from inversor.sources.banxico import SANITY, TITULO_DEBE_CONTENER

    for key in SERIES:
        assert TITULO_DEBE_CONTENER.get(key), f"{key} no tiene patrón de título"
        assert key in SANITY, f"{key} no tiene rango SANITY"


def test_inflacion_no_subyacente_es_rechazada_para_inpc():
    # El bug que existió: SP74665 con este título exacto.
    problemas = validate_series_title(
        "inpc_anual", "Inflación No subyacente (nueva definición) Anual"
    )
    assert any("subyacente" in p for p in problemas)


def test_inflacion_subyacente_tambien_es_rechazada_para_inpc():
    problemas = validate_series_title(
        "inpc_anual", "Inflación Subyacente (nueva definición) Anual"
    )
    assert any("subyacente" in p for p in problemas)


def test_titulo_con_plazo_equivocado_es_rechazado():
    # El título del 28d en la llave del 91d: mismo instrumento, plazo mal.
    problemas = validate_series_title("cetes_91", TITULOS_OFICIALES["cetes_28"])
    assert any("91 días" in p for p in problemas)


def test_familia_de_promedio_mensual_es_rechazada():
    # Título plausible de la familia SF282/SF3338: trae el plazo correcto pero
    # es promedio mensual, no la subasta primaria.
    problemas = validate_series_title(
        "cetes_28",
        "Cetes a 28 días - Promedio mensual - Tasa de rendimiento en subasta"
        " - Fecha subasta",
    )
    assert any("promedio" in p for p in problemas)


def test_familia_fechada_a_colocacion_es_rechazada():
    # La serie hermana del cuadro CF107: misma subasta, fechada a colocación
    # (jueves) en vez de a la subasta (martes). Reporta as_of ~2 días más
    # fresco de lo que el dato es y debilita el bloqueo por rancidez.
    problemas = validate_series_title(
        "cetes_28",
        "Valores gubernamentales, Resultados de la subasta semanal Cetes a 28 días"
        " - Tasa de rendimiento - Fecha de colocación",
    )
    assert any("fecha subasta" in p for p in problemas)


def test_validacion_es_case_insensitive():
    assert validate_series_title("tasa_objetivo", "TASA OBJETIVO") == []
    assert any(
        "subyacente" in p
        for p in validate_series_title("inpc_anual", "INFLACIÓN SUBYACENTE ANUAL")
    )


# ---------------- curva ----------------


def test_curva_real_de_subasta_pasa():
    validate_cetes_curve(CURVA_REAL)


def test_curva_invertida_pasa():
    # 2024 existió: tasas cortas arriba de las largas. Forma real, no error.
    validate_cetes_curve({28: 11.25, 91: 11.10, 182: 10.80, 364: 10.20})


def test_curva_plana_pasa():
    validate_cetes_curve({28: 7.0, 91: 7.0, 182: 7.0, 364: 7.0})


def test_hump_pequeno_dentro_de_tolerancia_pasa():
    # Un valle local en un ciclo de recortes es forma real: la peor caída
    # (30 pb) y la peor subida (20 pb) quedan ambas bajo tolerancia.
    validate_cetes_curve({28: 8.00, 91: 7.80, 182: 7.70, 364: 7.90})


def test_plazos_contiguos_intercambiados_truenan():
    # La curva real con 91d y 182d intercambiados. La cantidad operativa es el
    # diferencial real del par (35 pb): produce una caída de exactamente tol
    # entre pares, y la desigualdad estricta la cuenta como quiebre.
    curva = dict(CURVA_REAL)
    curva[91], curva[182] = curva[182], curva[91]
    with pytest.raises(BanxicoError, match="no monótona"):
        validate_cetes_curve(curva)


def test_frontera_estricta_tambien_del_lado_decreciente():
    # Espejo del anterior sobre curva invertida: el par intercambiado produce
    # una SUBIDA de exactamente tol (6.75-6.40) entre bajadas. Pinnea que la
    # rama decreciente usa la misma desigualdad estricta y el mismo redondeo
    # anti-float (6.75-6.40 = 0.34999... sin redondear).
    with pytest.raises(BanxicoError, match="no monótona"):
        validate_cetes_curve({28: 7.01, 91: 6.40, 182: 6.75, 364: 6.17})


def test_intercambio_con_diferencial_menor_a_tolerancia_pasa_y_es_limitacion():
    # Los intercambios 28↔91 (23 pb) y 182↔364 (26 pb) son, por forma,
    # indistinguibles de un valle genuino de ese tamaño: la curva NO los
    # atrapa y no puede atraparlos. Los atrapa validate_series_title leyendo
    # el plazo del título. Documentado como comportamiento, no sorpresa.
    swap_2891 = {28: 6.40, 91: 6.17, 182: 6.75, 364: 7.01}
    swap_182364 = {28: 6.17, 91: 6.40, 182: 7.01, 364: 6.75}
    validate_cetes_curve(swap_2891)
    validate_cetes_curve(swap_182364)


def test_dislocacion_en_un_extremo_truena():
    # cetes_364 apuntando a una serie de tasa baja: 3.00 pasa SANITY
    # (0.5, 30.0) y sólo viola la monotonía en UNA dirección. Con la versión
    # que acotaba pasos contiguos por rama, esto pasaba como "decreciente".
    # La ε-monotonía sobre todos los pares lo atrapa: sube +57 pb acumulados
    # y luego cae -374 pb; ninguna hipótesis aguanta.
    with pytest.raises(BanxicoError, match="no monótona"):
        validate_cetes_curve({28: 6.17, 91: 6.40, 182: 6.74, 364: 3.00})


def test_dislocacion_repartida_en_pasos_chicos_truena():
    # Deriva acumulada contra la dirección: ningún paso contiguo viola por sí
    # solo (-20, -20 pb), pero el par 28d→182d cae 40 pb bajo una curva que
    # termina subiendo 84 pb. Comparar sólo pasos contiguos la dejaba pasar.
    with pytest.raises(BanxicoError, match="no monótona"):
        validate_cetes_curve({28: 6.57, 91: 6.37, 182: 6.17, 364: 7.01})


def test_zigzag_grande_truena():
    with pytest.raises(BanxicoError, match="no monótona"):
        validate_cetes_curve({28: 6.17, 91: 7.30, 182: 6.20, 364: 7.01})


def test_curva_de_un_solo_plazo_no_truena():
    validate_cetes_curve({364: 7.01})
    validate_cetes_curve({})


def test_curva_totalmente_invertida_pasa_y_es_limitacion_documentada():
    # Las etiquetas al revés producen una curva monótona decreciente:
    # indistinguible de una inversión genuina. A esto NO lo atrapa la forma;
    # lo atrapa validate_series_title leyendo el plazo del título. Este test
    # existe para que la limitación quede escrita como comportamiento, no
    # como sorpresa.
    reversa = {28: 7.01, 91: 6.75, 182: 6.40, 364: 6.17}
    validate_cetes_curve(reversa)


# ---------------- verify-series como bloqueo ----------------


def _fake_catalogo(titulos: dict[str, str]):
    def fake_request(path: str, token: str, timeout: int = 20) -> dict:
        sid = path.rsplit("/", 1)[-1]
        key = next(k for k, s in SERIES.items() if s == sid)
        return {"bmx": {"series": [{"idSerie": sid, "titulo": titulos[key]}]}}

    return fake_request


def test_verify_series_sale_cero_con_el_catalogo_real(monkeypatch):
    from inversor import __main__ as cli

    monkeypatch.setenv("BANXICO_TOKEN", "token-de-prueba")
    monkeypatch.setattr(
        "inversor.sources.banxico._request", _fake_catalogo(TITULOS_OFICIALES)
    )
    assert cli.cmd_verify(None) == 0


def test_verify_series_bloquea_con_titulo_de_otra_serie(monkeypatch):
    # El bug histórico como lo vería verify-series: el ID de inpc_anual
    # devolviendo el título de la no subyacente. El cmd_verify anterior al
    # cambio imprimía la lista y salía 0 de todas formas; este test demuestra
    # que el bloqueo bloquea (regla de tests de CLAUDE.md).
    from inversor import __main__ as cli

    titulos = dict(TITULOS_OFICIALES)
    titulos["inpc_anual"] = "Inflación No subyacente (nueva definición) Anual"
    monkeypatch.setenv("BANXICO_TOKEN", "token-de-prueba")
    monkeypatch.setattr("inversor.sources.banxico._request", _fake_catalogo(titulos))
    assert cli.cmd_verify(None) == 1


def test_verify_series_bloquea_si_el_catalogo_no_responde(monkeypatch):
    from inversor import __main__ as cli

    def fallo(path: str, token: str, timeout: int = 20) -> dict:
        raise BanxicoError("HTTP 500 en /series/SF43718")

    monkeypatch.setenv("BANXICO_TOKEN", "token-de-prueba")
    monkeypatch.setattr("inversor.sources.banxico._request", fallo)
    assert cli.cmd_verify(None) == 1


# ---------------- integración con cetes_curve ----------------


def _obs_curva(valores: dict[str, float]) -> dict[str, Observation]:
    d = date(2026, 8, 10)
    return {k: Observation(k, "TEST", v, d, 1) for k, v in valores.items()}


def test_cetes_curve_valida_al_construir():
    obs = _obs_curva({"cetes_28": 6.17, "cetes_91": 7.30, "cetes_182": 6.20, "cetes_364": 7.01})
    with pytest.raises(BanxicoError, match="no monótona"):
        cetes_curve(obs)


def test_cetes_curve_sigue_devolviendo_decimales():
    obs = _obs_curva(
        {"cetes_28": 6.17, "cetes_91": 6.40, "cetes_182": 6.75, "cetes_364": 7.01}
    )
    curve = cetes_curve(obs)
    assert curve[364] == pytest.approx(0.0701)
    assert curve[28] == pytest.approx(0.0617)
