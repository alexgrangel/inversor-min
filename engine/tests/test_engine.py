"""
Tests offline. Cero red. Corren en CI y en tu Mac igual.

Lo que se prueba no es "el sistema gana dinero" — eso no se prueba con tests,
se prueba con el log walk-forward. Lo que se prueba aquí es que las invariantes
duras se respetan siempre:

  - El presupuesto de comisiones bloquea operar cuando está agotado.
  - Datos rancios bloquean la recomendación en vez de degradarla en silencio.
  - El peso cripto nunca supera el tope duro.
  - La aritmética fiscal es la de LISR (ISR sobre interés real, no nominal).
"""
from __future__ import annotations

import math
import random
from datetime import date

import pytest

from inversor.config import CostPolicy, Policy, Portfolio, RiskPolicy, TaxPolicy
from inversor.costs import compute_cost_budget, min_notional_ok
from inversor.decide import decide
from inversor.regime import classify
from inversor.risk import realized_vol, size_crypto_sleeve
from inversor.sources.banxico import Observation
from inversor.tax import (
    annualized_to_period,
    cetes_net_yield,
    crypto_effective_isr_rate,
    real_rate,
)


def synth(n=500, start=100.0, drift=0.0004, vol=0.03, seed=7):
    rng = random.Random(seed)
    out, p = [], start
    for _ in range(n):
        p *= math.exp(drift + rng.gauss(0, vol))
        out.append(p)
    return out


def obs(**over):
    base = {
        "fix_usdmxn": 17.1387,
        "cetes_28": 6.17,
        "cetes_91": 6.40,
        "cetes_182": 6.75,
        "cetes_364": 7.01,
        "tasa_objetivo": 6.50,
        "inpc_anual": 3.12,
    }
    base.update(over)
    d = date(2026, 8, 10)
    return {k: Observation(k, "TEST", v, d, 1) for k, v in base.items()}


# ---------------- fiscal ----------------

def test_real_rate_es_fisher_no_resta():
    r = real_rate(0.0701, 0.0312)
    assert r == pytest.approx((1.0701 / 1.0312) - 1, rel=1e-12)
    assert r < 0.0701 - 0.0312  # Fisher exacto < resta


def test_base_gravable_usa_la_resta_de_lisr_134_no_fisher():
    """La base del ISR es nominal − inflación (art. 134). Fisher es economía,
    no es la base fiscal. Confundirlas subestima el impuesto."""
    ny = cetes_net_yield(0.0701, 0.0312, TaxPolicy(marginal_isr_rate=0.30))
    assert ny.taxable_real_rate == pytest.approx(0.0701 - 0.0312, rel=1e-12)
    assert ny.taxable_real_rate > ny.real_rate_pretax  # la resta > Fisher
    assert ny.isr_on_real == pytest.approx(0.30 * (0.0701 - 0.0312), rel=1e-12)
    assert ny.isr_on_real < 0.30 * 0.0701  # y ambas << ISR sobre el nominal


def test_interes_real_negativo_no_genera_isr():
    ny = cetes_net_yield(0.03, 0.06, TaxPolicy(marginal_isr_rate=0.30))
    assert ny.isr_on_real == 0.0
    assert ny.net_nominal_rate == 0.03


def test_anualizada_a_periodo_no_es_regla_de_tres():
    """CETES 28d al 6.17% ANUAL no paga 6.17% en 28 días. Paga ~0.46%."""
    p = annualized_to_period(0.0617, 28)
    assert 0.0040 < p < 0.0050
    assert (1 + p) ** (365 / 28) == pytest.approx(1.0617, rel=1e-9)


def test_exencion_3xuma_cubre_capital_chico():
    t = TaxPolicy()
    rate, note = crypto_effective_isr_rate(8_000.0, t)
    assert rate == 0.0
    assert "exención" in note.lower()


def test_exencion_agotada_activa_isr_marginal():
    t = TaxPolicy(ganancias_cripto_ytd_mxn=128_383.92)
    rate, _ = crypto_effective_isr_rate(10_000.0, t)
    assert rate == pytest.approx(0.30, rel=1e-9)


# ---------------- costos ----------------

def test_presupuesto_se_define_sobre_el_sleeve_no_sobre_el_capital():
    """El presupuesto debe escalar con lo que rota. Definirlo sobre el capital
    total autorizaba comisiones equivalentes al 100% del exceso de rendimiento
    esperado de la posición."""
    b = compute_cost_budget(50_000.0, 5_000.0, CostPolicy())
    assert b.annual_budget_mxn == pytest.approx(25.0)      # 0.50% de 5,000
    assert b.cost_per_round_trip_pct == pytest.approx(0.0030)
    # 0.50% de presupuesto / 0.30% por round-trip = 1.67 operaciones al año.
    assert b.max_round_trips_per_year == pytest.approx(0.0050 / 0.0030, rel=1e-9)
    assert b.max_round_trips_per_year < 2.0


def test_sleeve_cero_no_inventa_operaciones_permitidas():
    b = compute_cost_budget(50_000.0, 0.0, CostPolicy())
    assert b.max_round_trips_per_year == 0.0
    assert b.cost_per_round_trip_mxn == 0.0


def test_presupuesto_agotado_se_detecta():
    b = compute_cost_budget(50_000.0, 40_000.0, CostPolicy(fees_spent_ytd_mxn=200.0))
    assert b.budget_exhausted is True


def test_min_notional_revisa_la_pata_mas_chica_no_el_promedio():
    """Con 400 MXN repartidos 75/25 el promedio pasa (11.67 USD) pero la pata
    de ETH da 5.83 USD y el venue la rechaza."""
    ok, note = min_notional_ok(400.0, 17.1387, (0.75, 0.25), CostPolicy())
    assert ok is False
    assert "5.8" in note


# ---------------- riesgo ----------------

def test_peso_nunca_supera_tope_duro():
    s = size_crypto_sleeve(45_000, vol_annual=0.05, vol_target=0.08,
                           max_dd_budget=0.50, assumed_asset_dd=0.75,
                           hard_cap=0.20, floor=0.03)
    assert s.weight <= 0.20 + 1e-12


def test_piso_lleva_posicion_a_cero():
    # Vol 400%: vol-target exige 0.08/4.0 = 2% de peso, por debajo del piso de 3%.
    s = size_crypto_sleeve(45_000, vol_annual=4.0, vol_target=0.08,
                           max_dd_budget=0.08, assumed_asset_dd=0.75,
                           hard_cap=0.20, floor=0.03)
    assert s.weight == 0.0
    assert s.binding_constraint == "below_floor"


def test_multiplicador_de_regimen_nunca_amplifica():
    a = size_crypto_sleeve(45_000, 0.45, 0.08, 0.08, 0.75, 0.20, 0.0, regime_multiplier=3.0)
    b = size_crypto_sleeve(45_000, 0.45, 0.08, 0.08, 0.75, 0.20, 0.0, regime_multiplier=1.0)
    assert a.weight == pytest.approx(b.weight)


def test_restriccion_reportada_es_la_que_realmente_manda():
    """Si el multiplicador de régimen recorta más que la restricción ganadora,
    reportar la restricción original le miente al usuario sobre por qué su
    posición es del tamaño que es."""
    s = size_crypto_sleeve(45_000, 0.45, 0.08, 0.08, 0.75, 0.20, 0.0,
                           regime_multiplier=0.45)
    assert "regime_multiplier" in s.binding_constraint
    assert s.weight == pytest.approx(min(0.08 / 0.45, 0.08 / 0.75, 0.20) * 0.45)


def test_multiplicador_combinado_es_el_minimo_como_dice_el_docstring():
    from inversor.regime import blended_multiplier

    class _S:
        def __init__(self, m): self.size_multiplier = m

    # BTC NEUTRAL (0.60) + ETH RISK_OFF (0.30) ⇒ 0.30, no 0.45.
    assert blended_multiplier([_S(0.60), _S(0.30)], [0.75, 0.25]) == pytest.approx(0.30)


def test_vol_realizada_es_positiva_y_anualizada():
    v = realized_vol(synth(vol=0.02))
    assert 0.10 < v < 1.5


# ---------------- régimen ----------------

def test_regimen_riesgo_on_en_tendencia_alcista():
    st = classify(synth(n=400, drift=0.003, vol=0.01, seed=1))
    assert st.label in ("RISK_ON", "NEUTRAL")
    assert st.size_multiplier <= 1.0


def test_regimen_risk_off_en_tendencia_bajista():
    st = classify(synth(n=400, drift=-0.004, vol=0.01, seed=2))
    assert st.label in ("RISK_OFF", "NEUTRAL", "STRESS")
    assert st.size_multiplier < 1.0


def test_serie_corta_truena_en_vez_de_adivinar():
    with pytest.raises(ValueError):
        classify(synth(n=100))


# ---------------- decisión end-to-end ----------------

def _closes():
    return {"BTC": synth(seed=3, vol=0.03), "ETH": synth(seed=4, vol=0.04)}


def test_decision_produce_hurdle_y_asignacion():
    d = decide(Policy(), obs(), _closes())
    assert d.hurdle["cetes_nominal"] == pytest.approx(0.0701)
    assert d.hurdle["hurdle_total_anualizado"] > d.hurdle["cetes_neto_nominal"]
    assert d.allocation_mxn
    assert sum(d.allocation_mxn.values()) == pytest.approx(50_000.0, abs=1.0)


def test_asignacion_siempre_suma_el_capital_total():
    """Incluso en la rama de presupuesto agotado, donde se pasa la posición
    ACTUAL, que puede exceder lo invertible."""
    p = Policy(cost=CostPolicy(fees_spent_ytd_mxn=10_000.0))
    for held in (0.0, 20_000.0, 46_000.0, 99_000.0):
        d = decide(p, obs(), _closes(), current_crypto_mxn=held)
        assert sum(d.allocation_mxn.values()) == pytest.approx(50_000.0, abs=1.0), d.action


def test_datos_rancios_bloquean_antes_de_calcular_nada():
    o = obs()
    o["inpc_anual"] = Observation("inpc_anual", "TEST", 3.12, date(2026, 1, 1), 221)
    d = decide(Policy(), o, _closes())
    assert d.action == "BLOCKED_STALE_DATA"
    assert d.blockers
    # Regla 4: bloquean, no degradan. Nada derivado de datos viejos se publica.
    assert d.hurdle == {}
    assert d.sizing == {}
    assert d.required_returns == {}
    assert d.allocation_mxn == {}


def test_hurdle_usa_el_plazo_que_calza_el_horizonte_y_lo_convierte():
    p = Policy(portfolio=Portfolio(total_capital_mxn=50_000, horizon_days=28))
    d = decide(p, obs(), _closes())
    assert d.hurdle["tenor_days"] == 28
    assert d.hurdle["cetes_nominal"] == pytest.approx(0.0617)
    # El hurdle del periodo debe ser MUCHO menor que el anualizado.
    assert d.hurdle["hurdle_total_periodo"] < d.hurdle["hurdle_total_anualizado"] / 10
    assert d.hurdle["hurdle_total_periodo"] < 0.02
    assert d.required_returns["rendimiento_mxn_requerido_periodo"] < 0.03


def test_presupuesto_agotado_bloquea_operacion():
    p = Policy(cost=CostPolicy(fees_spent_ytd_mxn=10_000.0))
    d = decide(p, obs(), _closes(), current_crypto_mxn=0.0)
    assert d.action == "BLOCKED_FEE_BUDGET"
    assert any("comisiones" in b.lower() for b in d.blockers)


def test_notional_minimo_bloquea_orden_inejecutable():
    p = Policy(
        portfolio=Portfolio(total_capital_mxn=9_000.0, horizon_days=364,
                            liquidity_reserve_mxn=1_000.0),
        risk=RiskPolicy(max_portfolio_drawdown_from_crypto=0.0625,
                        crypto_vol_target=0.08, min_crypto_weight=0.01),
    )
    d = decide(p, obs(), _closes())
    assert d.action == "BLOCKED_BELOW_MIN_NOTIONAL"
    assert d.blockers
    assert d.allocation_mxn["BTC"] == 0.0


def test_sensibilidad_fx_es_multiplicativa_no_resta():
    d = decide(Policy(), obs(), _closes())
    req = d.required_returns["rendimiento_mxn_requerido_periodo"]
    peor = next(s for s in d.fx["sensibilidad"] if s["escenario_mxn"] == -0.10)
    assert peor["rendimiento_usd_requerido"] == pytest.approx((1 + req) / 0.90 - 1, rel=1e-9)
    assert peor["rendimiento_usd_requerido"] > req - (-0.10) * -1  # estrictamente peor que la resta


def test_banda_de_no_operacion_evita_rebalanceo_marginal():
    p = Policy()
    d0 = decide(p, obs(), _closes(), current_crypto_mxn=0.0)
    target = d0.sizing["weight_mxn"]
    if target > 0:
        d1 = decide(p, obs(), _closes(), current_crypto_mxn=target * 0.95)
        assert d1.action == "HOLD_NO_ACTION"


def test_presupuesto_de_caida_estricto_manda_a_cetes():
    p = Policy(risk=RiskPolicy(max_portfolio_drawdown_from_crypto=0.005,
                               min_crypto_weight=0.03))
    d = decide(p, obs(), _closes())
    assert d.action == "STAY_IN_CETES"
    assert d.allocation_mxn["BTC"] == 0.0


def test_snapshot_es_serializable():
    import json
    d = decide(Policy(), obs(), _closes())
    json.dumps(d.to_json_dict(), ensure_ascii=False)


# ---------------- frescura de precios y venues ----------------

def test_precios_rancios_bloquean_igual_que_los_datos_macro():
    """Antes los timestamps de las velas se descartaban: una serie congelada
    era indistinguible de una fresca y el motor dimensionaba sobre precios
    viejos reportando stale:false. Regla 4."""
    d = decide(
        Policy(), obs(), _closes(),
        today=date(2026, 8, 10),
        closes_as_of={"BTC": date(2026, 7, 1), "ETH": date(2026, 8, 9)},
        venues={"BTC": "kraken", "ETH": "kraken"},
    )
    assert d.action == "BLOCKED_STALE_DATA"
    assert any("precio BTC" in b for b in d.blockers)
    assert d.hurdle == {}          # no se calcula nada sobre datos rancios


def test_precios_frescos_no_bloquean_y_el_venue_queda_registrado():
    d = decide(
        Policy(), obs(), _closes(),
        today=date(2026, 8, 10),
        closes_as_of={"BTC": date(2026, 8, 9), "ETH": date(2026, 8, 9)},
        venues={"BTC": "kraken", "ETH": "coinbase"},
    )
    assert d.action != "BLOCKED_STALE_DATA"
    # El venue va al snapshot: un cambio de fuente de precios es una
    # discontinuidad de datos y tiene que ser visible en el log walk-forward.
    assert d.market["venues"] == {"BTC": "kraken", "ETH": "coinbase"}
    assert d.data_freshness["precio_BTC"]["series_id"] == "kraken:BTC"


def test_cada_venue_traduce_el_activo_canonico():
    from inversor.sources.market_data import VENUE_SYMBOLS
    for venue in ("kraken", "coinbase", "binance"):
        assert set(VENUE_SYMBOLS[venue]) == {"BTC", "ETH"}
    assert VENUE_SYMBOLS["kraken"]["BTC"] == "XBTUSD"
    assert VENUE_SYMBOLS["coinbase"]["BTC"] == "BTC-USD"


def test_binance_va_al_final_del_orden_de_venues():
    """Binance devuelve 451 desde IPs de EE.UU. y los runners de GitHub
    Actions son estadounidenses. No puede ser el primario."""
    orden = Policy().universe.venue_order
    assert orden[0] == "kraken"
    assert orden[-1] == "binance"
