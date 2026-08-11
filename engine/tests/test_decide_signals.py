"""
La conexión señales → decide() (Prompt 5). El test que importa es el primero:
sobre decide() COMPLETO, ninguna combinación de señales de noticias/estrés
puede producir un peso cripto MAYOR que el que produce el motor sin ellas.
Esa es la regla 8, y es la que hace que esta feature no sea una máquina de
sobreoperar.
"""
from __future__ import annotations

import json
import random
from datetime import date

import pytest

from inversor.config import Policy
from inversor.decide import decide
from inversor.signals import SignalState, combinar
from inversor.sources import market_stress as ms
from inversor.sources import news as nw

from test_engine import _closes, obs

HOY = date(2026, 8, 10)


def _peso_cripto_mxn(d) -> float:
    return sum(v for k, v in d.allocation_mxn.items() if k in ("BTC", "ETH"))


def _lectura(key: str, value, stale_days=1) -> ms.StressReading:
    return ms.StressReading(
        key=key, source="fx", series_id="TEST", value=value, as_of=HOY,
        stale_days=stale_days, label="",
    )


class _Basura:
    """Objeto con forma equivocada: sin value, sin stale_days, sin nada."""


def _estados_adversariales(n: int, seed: int = 11) -> list[SignalState]:
    """
    SignalStates por las dos vías: construidos a mano con multiplicadores
    absurdos (el clamp vive en el tipo) y salidos de combinar() con entradas
    basura (el clamp vive en el combinador). El motor debe aguantar ambos.
    """
    rng = random.Random(seed)
    absurdos = [7.0, -3.0, float("inf"), float("-inf"), float("nan"), 10**400,
                1.0000001, 0.999999, "2.5", None, 1e308]
    estados: list[SignalState] = [SignalState(multiplicador=m) for m in absurdos]  # type: ignore[arg-type]

    valores_locos = [None, float("nan"), -50.0, 0.0, 101.0, 10**9, "miedo", _Basura()]
    for _ in range(n):
        estados.append(
            combinar(
                fear_greed=rng.choice([None, _Basura(), _lectura("fear_greed", rng.choice(valores_locos))]),
                dvol=rng.choice([None, _lectura("dvol_btc", rng.choice(valores_locos), stale_days=rng.choice([1, 400]))]),
                vix=rng.choice([None, _lectura("vix", rng.choice(valores_locos))]),
                volumen=rng.choice([None, _Basura()]),
                ruptura=rng.choice([None, _Basura()]),
                fuentes_no_disponibles=rng.choice([(), None, ["x: caída"], [_Basura()], "una"]),
                hoy=HOY,
            )
        )
    return estados


def test_regla8_ninguna_senal_aumenta_el_peso_sobre_decide_completo():
    base = decide(Policy(), obs(), _closes(), today=HOY)
    peso_base = _peso_cripto_mxn(base)
    assert peso_base > 0  # si el motor sin señales no asigna nada, el test no prueba nada

    for st in _estados_adversariales(150):
        d = decide(Policy(), obs(), _closes(), today=HOY, signal_state=st)
        assert _peso_cripto_mxn(d) <= peso_base + 1e-9, st.to_json_dict()
        if d.sizing:
            assert d.sizing["combined_multiplier"] <= d.sizing["regime_multiplier"] + 1e-12


def test_composicion_es_minimo_no_producto():
    base = decide(Policy(), obs(), _closes(), today=HOY)
    regimen = base.sizing["regime_multiplier"]
    assert 0.0 < regimen <= 1.0

    # Señales MENOS restrictivas que el régimen: el mínimo es el régimen y el
    # producto sería menor. Si alguien "arregla" aplicar() a producto, el
    # combinado deja de ser igual al régimen y esto truena.
    suaves = SignalState(multiplicador=min(1.0, regimen + 0.3))
    d1 = decide(Policy(), obs(), _closes(), today=HOY, signal_state=suaves)
    assert d1.sizing["combined_multiplier"] == pytest.approx(regimen)
    assert _peso_cripto_mxn(d1) == pytest.approx(_peso_cripto_mxn(base))

    # Señales MÁS restrictivas: manda la señal, no el producto.
    duras = SignalState(multiplicador=regimen / 2)
    d2 = decide(Policy(), obs(), _closes(), today=HOY, signal_state=duras)
    assert d2.sizing["combined_multiplier"] == pytest.approx(regimen / 2)
    assert d2.sizing["combined_multiplier"] > regimen * (regimen / 2) - 1e-12 or regimen == 1.0


def test_ruptura_estructural_bloquea_antes_de_calcular():
    c = nw.Coincidencia(
        etiqueta="SAT publica criterio o regla sobre activos virtuales",
        fuente="expansion", titulo="El SAT publica criterio sobre activos virtuales",
        url="https://example.invalid/x", fecha=HOY, terminos=("sat", "activos virtuales"),
    )
    ruptura = nw.RupturaEstructural(True, True, (c,), ("expansion",), 40, "fixture")
    st = combinar(
        fear_greed=_lectura("fear_greed", 60.0), dvol=_lectura("dvol_btc", 45.0),
        vix=_lectura("vix", 15.0), volumen=None, ruptura=ruptura,
        apagadas=["volumen_noticias"], hoy=HOY,
    )
    assert st.blockers

    d = decide(Policy(), obs(), _closes(), today=HOY, signal_state=st)
    assert d.action == "BLOCKED_STRUCTURAL_BREAK"
    assert any("RUPTURA ESTRUCTURAL" in b for b in d.blockers)
    assert any("revisión humana" in b for b in d.blockers)
    # Bloquea ANTES de calcular: nada derivado se publica (regla 4/6).
    assert d.hurdle == {}
    assert d.sizing == {}
    assert d.allocation_mxn == {}


def test_fuentes_caidas_entran_a_warnings_y_recortan_desde_decide():
    st = combinar(
        fear_greed=None, dvol=None, vix=_lectura("vix", 15.0),
        volumen=None, ruptura=nw.RupturaEstructural(True, False, (), ("expansion",), 30, ""),
        apagadas=["volumen_noticias"], hoy=HOY,
    )
    base = decide(Policy(), obs(), _closes(), today=HOY)
    d = decide(Policy(), obs(), _closes(), today=HOY, signal_state=st)

    assert any("fuente no disponible" in w for w in d.warnings)
    assert d.sizing["signals_multiplier"] == pytest.approx(0.60)
    assert _peso_cripto_mxn(d) <= _peso_cripto_mxn(base) + 1e-9


def test_fuente_apagada_no_es_ceguera_pero_tampoco_calma():
    # GDELT y DOF apagados por bandera + FRED sin llave: la ÚNICA caída real
    # es el vix. Antes del estado "apagada", esto recortaba a 0.60x
    # permanentemente y el recorte dejaba de ser información.
    st = combinar(
        fear_greed=_lectura("fear_greed", 60.0), dvol=_lectura("dvol_btc", 45.0),
        vix=None,
        volumen=None,
        ruptura=nw.RupturaEstructural(True, False, (), ("expansion",), 30, ""),
        apagadas=["volumen_noticias"], hoy=HOY,
    )
    assert st.multiplicador == pytest.approx(1.0)
    assert any("apagada" in r for r in st.razones)
    # Y la apagada no aparece como no-disponible: no opina, no es ceguera.
    assert not any("volumen_noticias" in f for f in st.fuentes_no_disponibles)


def test_una_fuente_caida_dos_renglones_no_dispara_el_recorte():
    # El recolector reporta 'vix: FRED caído' Y el slot en None agrega
    # 'vix: sin dato.': una sola fuente real, dos renglones. El umbral cuenta
    # fuentes únicas; contar renglones disparaba 0.60x con una sola caída.
    st = combinar(
        fear_greed=_lectura("fear_greed", 60.0), dvol=_lectura("dvol_btc", 45.0),
        vix=None,
        volumen=nw.VolumenAnomalo(True, False, 0.1, 1.0, 1.0, 0.1, 20, HOY, "fx"),
        ruptura=nw.RupturaEstructural(True, False, (), ("expansion",), 30, ""),
        fuentes_no_disponibles=["vix: falta FRED_API_KEY"],
        hoy=HOY,
    )
    assert st.multiplicador == pytest.approx(1.0)

    # Dos fuentes DISTINTAS sí recortan.
    st2 = combinar(
        fear_greed=None, dvol=_lectura("dvol_btc", 45.0), vix=None,
        volumen=nw.VolumenAnomalo(True, False, 0.1, 1.0, 1.0, 0.1, 20, HOY, "fx"),
        ruptura=nw.RupturaEstructural(True, False, (), ("expansion",), 30, ""),
        fuentes_no_disponibles=["vix: falta FRED_API_KEY"],
        hoy=HOY,
    )
    assert st2.multiplicador == pytest.approx(0.60)


def test_eventos_en_el_snapshot_con_banxico_y_escenarios():
    d = decide(Policy(), obs(), _closes(), today=HOY)
    assert d.eventos["proximos"], "la ventana de 60 días debe traer eventos"
    banxico = [e for e in d.eventos["proximos"] if e["tipo"] == "BANXICO"]
    assert banxico and banxico[0]["fecha"] == "2026-09-24"

    esc = d.eventos["escenarios_banxico"]
    movimientos = {e["movimiento_bp"] for e in esc}
    assert {-50, -25, 0, 25} <= movimientos
    sin_cambio = next(e for e in esc if e["movimiento_bp"] == 0)
    assert sin_cambio["hurdle_anualizado"] == pytest.approx(
        d.hurdle["hurdle_total_anualizado"], abs=1e-9
    )
    assert any("Banxico decide el 2026-09-24" in r for r in d.reasons)

    # Todo el snapshot, incluidos eventos y señales, es JSON serializable.
    st = combinar(hoy=HOY)
    d2 = decide(Policy(), obs(), _closes(), today=HOY, signal_state=st)
    json.dumps(d2.to_json_dict(), ensure_ascii=False)


def test_snapshot_previo_301_sin_campos_aditivos_rehidrata(tmp_path):
    # El snapshot real de hoy es 3.0.0 y no trae signals/eventos: mañana el
    # cron 3.1.0 lo lee como previo. Sin este comportamiento, la primera
    # corrida después de CADA adición de campos moría con ValueError.
    from inversor.__main__ import _load_previous_decision


    d = decide(Policy(), obs(), _closes(), today=HOY)
    viejo = d.to_json_dict()
    viejo["schema_version"] = "3.0.0"
    del viejo["signals"]
    del viejo["eventos"]
    (tmp_path / "latest.json").write_text(
        json.dumps(viejo, ensure_ascii=False), encoding="utf-8"
    )
    previo = _load_previous_decision(tmp_path, d)
    assert previo is not None
    assert previo.signals == {} and previo.eventos == {}
