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


# ---------------- títulos ----------------


def test_titulos_oficiales_reales_pasan_todos():
    for key in SERIES:
        assert validate_series_title(key, TITULOS_OFICIALES[key]) == [], key


def test_toda_serie_tiene_patron_de_titulo_requerido():
    # Una llave nueva sin patrón pasaría la validación con cualquier título.
    from inversor.sources.banxico import TITULO_DEBE_CONTENER

    for key in SERIES:
        assert TITULO_DEBE_CONTENER.get(key), f"{key} no tiene patrón de título"


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
        "cetes_28", "Cetes a 28 días - Promedio mensual - Tasa de rendimiento en subasta"
    )
    assert any("promedio" in p for p in problemas)


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
    # Un valle local de 10 pb en un ciclo de recortes es forma real.
    validate_cetes_curve({28: 8.00, 91: 7.80, 182: 7.70, 364: 7.90})


def test_plazos_contiguos_intercambiados_truenan():
    # La curva real con 91d y 182d intercambiados: quiebre de -35 pb entre
    # subidas. Es exactamente el caso que la tolerancia estricta debe atrapar.
    curva = dict(CURVA_REAL)
    curva[91], curva[182] = curva[182], curva[91]
    with pytest.raises(BanxicoError, match="no monótona"):
        validate_cetes_curve(curva)


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
