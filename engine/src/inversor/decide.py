"""
La compuerta. Junta todo y emite UNA decisión con su razonamiento explícito.

Principio no negociable: este módulo NO pronostica rendimientos. Hace cuatro
cosas y ninguna más:

  1. Calcula el costo de oportunidad libre de riesgo, neto de impuestos (CETES).
  2. Dimensiona cuánto riesgo cripto cabe dentro de tu presupuesto de pérdida.
  3. Impone un techo duro de comisiones y bloquea la operación si ya lo gastaste.
  4. Te dice qué tan grande tiene que ser el movimiento para que la apuesta
     hubiera valido la pena. Si el número es absurdo, la respuesta es CETES.

La salida más frecuente y más valiosa de este sistema es STAY_IN_CETES.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from . import events as ev
from .config import SCHEMA_VERSION, Policy
from .costs import CostBudget, compute_cost_budget, min_notional_ok
from .regime import RegimeState, blended_multiplier, classify
from .risk import Sizing, size_crypto_sleeve
from .signals import SignalState
from .sources import banxico as bx
from .tax import annualized_to_period, crypto_effective_isr_rate, hurdle_rate

# Banda de no-operación: por debajo de esto, el costo de rebalancear supera
# el beneficio de corregir la desviación.
REBALANCE_BAND_RELATIVE = 0.25

# Ventana del calendario de eventos en el snapshot. 60 y no 30: la separación
# máxima entre juntas consecutivas de Banxico en 2026 es de 42 días (24-sep →
# 5-nov → 17-dic), así que 60 garantiza que la próxima decisión de tasa SIEMPRE
# aparezca con sus escenarios precalculados; con 30, agosto se quedaba sin ver
# la junta de septiembre. Juicio de ventana, no dato (regla 5).
EVENTOS_VENTANA_DIAS = 60


@dataclass
class Decision:
    schema_version: str
    generated_at: str
    action: str
    headline: str
    reasons: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    market: dict[str, Any] = field(default_factory=dict)
    hurdle: dict[str, Any] = field(default_factory=dict)
    sizing: dict[str, Any] = field(default_factory=dict)
    costs: dict[str, Any] = field(default_factory=dict)
    allocation_mxn: dict[str, float] = field(default_factory=dict)
    required_returns: dict[str, Any] = field(default_factory=dict)
    fx: dict[str, Any] = field(default_factory=dict)
    data_freshness: dict[str, Any] = field(default_factory=dict)
    # Aditivos en 3.1.0: señales de estrés/noticias y calendario de eventos.
    signals: dict[str, Any] = field(default_factory=dict)
    eventos: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict:
        return asdict(self)


def _freshness(obs: dict[str, bx.Observation], policy: Policy) -> tuple[dict, list[str]]:
    # El límite es POR SERIE: "rancio" depende del calendario de publicación
    # de cada fuente (la subasta de CETES es semanal, el INPC mensual). Un
    # límite uniforme convertía el calendario normal en bloqueo permanente.
    out, stale = {}, []
    for k, o in obs.items():
        max_days = policy.staleness_limit(k)
        out[k] = {
            "series_id": o.series_id,
            "value": o.value,
            "as_of": o.as_of.isoformat(),
            "stale_days": o.stale_days,
            "stale": o.stale_days > max_days,
        }
        if o.stale_days > max_days:
            stale.append(f"{k}: {o.stale_days} días de antigüedad (límite {max_days}).")
    return out, stale


def decide(
    policy: Policy,
    obs: dict[str, bx.Observation],
    closes_by_symbol: dict[str, list[float]],
    current_crypto_mxn: float = 0.0,
    today: date | None = None,
    closes_as_of: dict[str, date] | None = None,
    venues: dict[str, str] | None = None,
    signal_state: SignalState | None = None,
) -> Decision:
    today = today or date.today()
    d = Decision(
        schema_version=SCHEMA_VERSION,
        generated_at=datetime.now(timezone.utc).isoformat(),
        action="STAY_IN_CETES",
        headline="",
        policy=policy.to_dict(),
    )

    # ---------- 1. Datos y frescura ----------
    # El bloqueo por datos rancios ocurre AQUÍ, antes de calcular nada.
    # Antes se calculaba todo y se bloqueaba al final, dejando el snapshot
    # lleno de hurdle, sizing y required_returns derivados de datos viejos.
    # Regla 4 de CLAUDE.md: los datos rancios bloquean, no degradan.
    d.data_freshness, stale = _freshness(obs, policy)

    # Frescura de PRECIOS. Antes no se revisaba: __main__ tiraba los timestamps
    # de las velas y una serie congelada o cacheada era indistinguible de una
    # fresca. El motor habría dimensionado una posición sobre precios de hace un
    # mes reportando `stale: false`. Regla 4.
    for sym, as_of in (closes_as_of or {}).items():
        edad = (today - as_of).days
        venue = (venues or {}).get(sym, "?")
        d.data_freshness[f"precio_{sym}"] = {
            "series_id": f"{venue}:{sym}",
            "value": closes_by_symbol.get(sym, [float("nan")])[-1],
            "as_of": as_of.isoformat(),
            "stale_days": edad,
            "stale": edad > policy.max_staleness_days,
        }
        if edad > policy.max_staleness_days:
            stale.append(
                f"precio {sym} ({venue}): {edad} días de antigüedad"
                f" (límite {policy.max_staleness_days})."
            )
    if stale:
        d.action = "BLOCKED_STALE_DATA"
        d.blockers.extend(stale)
        d.headline = "Datos rancios. No se emite recomendación ni se calcula nada más."
        return d

    # ---------- 1b. Señales de estrés y noticias ----------
    # Las señales sólo pueden REDUCIR el tamaño o BLOQUEAR (regla 8). El
    # multiplicador se compone más abajo, en el paso 3; aquí entran al
    # snapshot, las fuentes caídas a warnings, y la ruptura estructural
    # bloquea ANTES de calcular nada: invalida el MODELO (fiscal/regulatorio),
    # no el precio — nada de lo que sigue sobrevive a eso.
    if signal_state is not None:
        d.signals = signal_state.to_json_dict()
        d.warnings.extend(
            f"Señales — fuente no disponible: {f}"
            for f in signal_state.fuentes_no_disponibles
        )
        if signal_state.blockers:
            d.action = "BLOCKED_STRUCTURAL_BREAK"
            d.blockers.extend(signal_state.blockers)
            d.headline = (
                "Ruptura estructural detectada. Lo que está en duda es el modelo"
                " (fiscal o regulatorio), no el precio. Revisión humana antes de"
                " operar; ningún multiplicador resuelve esto."
            )
            return d

    fix = obs["fix_usdmxn"].value
    inflation = obs["inpc_anual"].value / 100.0
    curve = bx.cetes_curve(obs)
    tenor, cetes_nominal = bx.pick_hurdle_tenor(curve, policy.portfolio.horizon_days)

    d.market = {
        "usdmxn_fix": fix,
        "usdmxn_fix_as_of": obs["fix_usdmxn"].as_of.isoformat(),
        "inflacion_anual": inflation,
        "tasa_objetivo": obs["tasa_objetivo"].value / 100.0 if "tasa_objetivo" in obs else None,
        "cetes_curve": {str(k): v for k, v in curve.items()},
        # Qué venue sirvió cada precio. Un cambio de fuente es una
        # discontinuidad en los datos, no un detalle de infraestructura.
        "venues": dict(venues or {}),
    }

    # ---------- 2. Hurdle ----------
    # TODAS las tasas de aquí para abajo son ANUALIZADAS. La conversión al
    # horizonte real se hace UNA vez, explícitamente, en el paso 5. Mezclar
    # una tasa anual con un rendimiento de 28 días era el peor bug del motor:
    # con horizonte de 28 días publicaba "necesitas 10.84% en 28 días", que
    # anualizado es 283%. Un hurdle imposible por construcción.
    horizon = policy.portfolio.horizon_days
    hurdle_annual, ny = hurdle_rate(
        cetes_nominal, inflation, policy.tax, policy.required_risk_premium
    )
    hurdle_period = annualized_to_period(hurdle_annual, horizon)

    d.hurdle = {
        "tenor_days": tenor,
        "horizon_days": horizon,
        "cetes_nominal": ny.nominal_rate,
        "inflacion": ny.inflation_rate,
        "cetes_real_pretax": ny.real_rate_pretax,
        "base_gravable_lisr134": ny.taxable_real_rate,
        "isr_sobre_interes_real": ny.isr_on_real,
        "cetes_neto_nominal": ny.net_nominal_rate,
        "cetes_neto_real": ny.net_real_rate,
        "prima_de_riesgo_exigida": policy.required_risk_premium,
        "hurdle_total_anualizado": hurdle_annual,
        "hurdle_total_periodo": hurdle_period,
        "assumptions": list(ny.assumptions),
    }
    d.reasons.append(
        f"Hurdle: CETES {tenor}d al {ny.nominal_rate:.2%} nominal → {ny.net_nominal_rate:.2%}"
        f" neto de ISR ({ny.net_real_rate:.2%} real). Más prima de riesgo de"
        f" {policy.required_risk_premium:.2%} = {hurdle_annual:.2%} anualizado,"
        f" equivalente a {hurdle_period:.2%} en {horizon} días."
    )

    investable = max(
        policy.portfolio.total_capital_mxn - policy.portfolio.liquidity_reserve_mxn, 0.0
    )

    # ---------- 3. Régimen y dimensionamiento ----------
    states: list[RegimeState] = []
    weights = list(policy.universe.crypto_weights)
    for sym in policy.universe.crypto_symbols:
        closes = closes_by_symbol.get(sym, [])
        try:
            states.append(classify(closes))
        except ValueError as e:
            d.blockers.append(f"{sym}: {e}")
    if d.blockers:
        d.action = "BLOCKED_STALE_DATA"
        d.headline = "Datos de mercado insuficientes. Sin recomendación."
        return d

    mult_regimen = blended_multiplier(states, weights)
    vol_blend = sum(s.vol_30d * w for s, w in zip(states, weights))

    # Señales y régimen leen el MISMO estado de estrés por ventanas distintas:
    # se componen por MÍNIMO (manda el que más aprieta), no por producto — el
    # producto contaría el mismo estrés dos veces.
    mult = signal_state.aplicar(mult_regimen) if signal_state is not None else mult_regimen

    sizing: Sizing = size_crypto_sleeve(
        investable_mxn=investable,
        vol_annual=vol_blend,
        vol_target=policy.risk.crypto_vol_target,
        max_dd_budget=policy.risk.max_portfolio_drawdown_from_crypto,
        assumed_asset_dd=policy.risk.assumed_crypto_max_drawdown,
        hard_cap=policy.risk.max_crypto_weight,
        floor=policy.risk.min_crypto_weight,
        regime_multiplier=mult,
    )
    d.sizing = {
        **{k: v for k, v in asdict(sizing).items() if k != "notes"},
        "notes": list(sizing.notes),
        "regime_multiplier": mult_regimen,
        "signals_multiplier": signal_state.multiplicador if signal_state is not None else None,
        "combined_multiplier": mult,
        "regimes": [
            {**{k: v for k, v in asdict(s).items() if k != "signals"}, "signals": list(s.signals)}
            for s in states
        ],
    }
    d.reasons.extend(sizing.notes)
    if signal_state is not None:
        d.reasons.extend(signal_state.razones)
        if mult < mult_regimen:
            d.reasons.append(
                f"Las señales aprietan más que el régimen: multiplicador combinado"
                f" {mult:.2f} = min(régimen {mult_regimen:.2f}, señales"
                f" {signal_state.multiplicador:.2f})."
            )

    target_sleeve = sizing.weight_mxn

    # ---------- 3b. Eventos de calendario ----------
    # El reemplazo honesto del "tiempo real": no sabemos qué hará Banxico,
    # sabemos exactamente CUÁNDO. Los escenarios son declarados, no
    # pronósticos (regla 1) — la verificación cruzada de escenarios_banxico
    # truena si el escenario "sin cambio" no reproduce el hurdle de arriba.
    proximos = ev.proximos_eventos(today=today, dias=EVENTOS_VENTANA_DIAS)
    escenarios = ev.escenarios_banxico(
        hurdle_annual, curve, policy, inflation,
        vol_annual=vol_blend, multiplicador=mult,
    )
    d.eventos = {
        "ventana_dias": EVENTOS_VENTANA_DIAS,
        "proximos": [
            {
                "fecha": e.fecha.isoformat(),
                "tipo": e.tipo,
                "nombre": e.nombre,
                "fuente": e.fuente,
                "verificado": e.verificado,
                "fecha_fin": e.fecha_fin.isoformat() if e.fecha_fin else None,
                "nota": e.nota,
            }
            for e in proximos
        ],
        "escenarios_banxico": [
            {**{k: v for k, v in asdict(x).items() if k != "supuestos"},
             "supuestos": list(x.supuestos)}
            for x in escenarios
        ],
    }
    for e in proximos:
        if e.tipo == "CALENDARIO_AGOTADO":
            d.warnings.append(e.nota or e.nombre)
    banxico_prox = next((e for e in proximos if e.tipo == "BANXICO"), None)
    recorte_50 = next((x for x in escenarios if x.movimiento_bp == -50), None)
    if banxico_prox and recorte_50:
        d.reasons.append(
            f"Banxico decide el {banxico_prox.fecha.isoformat()}. Si recorta 50 pb,"
            f" el hurdle anualizado baja de {hurdle_annual:.2%} a"
            f" {recorte_50.hurdle_anualizado:.2%} y el sleeve objetivo pasa a"
            f" {recorte_50.sleeve_objetivo_mxn:,.0f} MXN"
            f" ({recorte_50.delta_sleeve_mxn:+,.0f}). Escenario declarado con la"
            " curva de hoy, no pronóstico."
        )

    # ---------- 4. Presupuesto de comisiones ----------
    # Sin max(target_sleeve, 1.0): inventar un sleeve de 1 peso producía
    # "83,333 operaciones permitidas al año" en el reporte al usuario.
    budget: CostBudget = compute_cost_budget(
        policy.portfolio.total_capital_mxn, target_sleeve, policy.cost
    )
    d.costs = {**{k: v for k, v in asdict(budget).items() if k != "notes"}, "notes": list(budget.notes)}
    d.reasons.extend(budget.notes)

    # ---------- 5. Rendimiento requerido ----------
    # El costo de comisiones es un evento ÚNICO (entrar y salir), no una tasa
    # anual: se suma al hurdle YA convertido al periodo, nunca al anualizado.
    fee_drag_on_sleeve = budget.cost_per_round_trip_pct
    isr_cripto, isr_note = crypto_effective_isr_rate(
        expected_gain_mxn=max(target_sleeve * hurdle_period, 0.0), tax=policy.tax
    )
    required_mxn = (
        (hurdle_period + fee_drag_on_sleeve) / (1.0 - isr_cripto)
        if isr_cripto < 1
        else float("inf")
    )
    d.required_returns = {
        "hurdle_periodo": hurdle_period,
        "hurdle_anualizado": hurdle_annual,
        "horizon_days": horizon,
        "fee_drag_round_trip": fee_drag_on_sleeve,
        "isr_efectivo_cripto": isr_cripto,
        "isr_nota": isr_note,
        "rendimiento_mxn_requerido_periodo": required_mxn,
        "rendimiento_mxn_requerido_anualizado": (1.0 + required_mxn) ** (365 / horizon) - 1.0,
        "explicacion": (
            f"Para que el sleeve cripto haya valido la pena frente a CETES, tiene que rendir"
            f" al menos {required_mxn:.2%} EN PESOS en {horizon} días."
            " Ese rendimiento en pesos es rendimiento en dólares MÁS movimiento del tipo de cambio."
        ),
    }
    d.reasons.append(d.required_returns["explicacion"])
    d.reasons.append(isr_note)

    # ---------- 5b. Materialidad ----------
    # A capital chico la pregunta no es "¿sube o baja?" sino "¿me cambia la vida
    # si acierto?". Si la respuesta es no, la posición sólo agrega ruido y trabajo.
    total = policy.portfolio.total_capital_mxn
    w_total = (target_sleeve / total) if total > 0 else 0.0
    # CETES sólo se paga sobre lo INVERTIBLE. La reserva de liquidez no genera
    # rendimiento; incluirla inflaba la comparación 11.9% a favor de CETES.
    cetes_anual = (investable - target_sleeve) * ny.net_nominal_rate
    d.sizing["materiality"] = {
        "peso_sobre_capital_total": w_total,
        "escenarios": [
            {
                "movimiento_cripto": mv,
                "impacto_portafolio_pct": w_total * mv,
                "impacto_portafolio_mxn": target_sleeve * mv,
            }
            for mv in (-0.50, -0.25, 0.25, 0.50, 1.00)
        ],
        "cetes_anual_mxn": cetes_anual,
        "veredicto": (
            "MATERIAL" if abs(w_total * 0.50) >= 0.02 else "INMATERIAL"
        ),
    }
    if d.sizing["materiality"]["veredicto"] == "INMATERIAL":
        d.warnings.append(
            f"Sleeve de {target_sleeve:,.0f} MXN: aun con cripto +50%, el impacto en el"
            f" portafolio total es {w_total * 0.50:+.2%}. Es ruido. Considera no tener"
            " la posición y ahorrarte el trabajo operativo y fiscal."
        )

    # ---------- 6. FX: la variable que casi nadie modela ----------
    d.fx = {
        "usdmxn_fix": fix,
        # Álgebra multiplicativa, no resta: (1+r_mxn)/(1+fx) − 1.
        # La resta subestimaba 238 pb justo en el escenario adverso
        # (peso apreciándose), que es el que más importa: el peso se apreció
        # 1.69% en los últimos 30 días.
        "sensibilidad": [
            {
                "escenario_mxn": pct,
                "rendimiento_usd_requerido": (1.0 + required_mxn) / (1.0 + pct) - 1.0,
                "nota": (
                    f"Si el peso se aprecia {abs(pct):.0%}, cripto necesita"
                    f" {(1.0 + required_mxn) / (1.0 + pct) - 1.0:.2%} en USD sólo para"
                    " empatar a CETES."
                    if pct < 0
                    else f"Si el peso se deprecia {pct:.0%}, el requerido en USD baja a"
                    f" {(1.0 + required_mxn) / (1.0 + pct) - 1.0:.2%}."
                ),
            }
            for pct in (-0.10, -0.05, 0.0, 0.05, 0.10)
        ],
        "advertencia": (
            "Tienes ingresos y gastos en MXN. Una posición cripto es una posición"
            " larga en USD sin cobertura. A tu tamaño de cuenta, la volatilidad"
            " del tipo de cambio es comparable al alfa que puedes esperar."
        ),
    }
    d.warnings.append(d.fx["advertencia"])

    # ---------- 7. Bloqueos duros ----------
    if target_sleeve <= 0:
        d.action = "STAY_IN_CETES"
        d.allocation_mxn = _allocation(policy, investable, 0.0, curve, tenor)
        d.headline = (
            f"Todo a CETES {tenor}d. El dimensionamiento por riesgo no justifica"
            " posición cripto en este régimen."
        )
        return d

    ok, note = min_notional_ok(target_sleeve, fix, policy.universe.crypto_weights, policy.cost)
    d.costs["min_notional_check"] = note
    if not ok:
        d.action = "BLOCKED_BELOW_MIN_NOTIONAL"
        d.blockers.append(note)
        d.allocation_mxn = _allocation(policy, investable, 0.0, curve, tenor)
        d.headline = "Posición por debajo del mínimo operable del venue. Todo a CETES."
        return d

    if budget.budget_exhausted and abs(current_crypto_mxn - target_sleeve) > 0:
        d.action = "BLOCKED_FEE_BUDGET"
        d.blockers.append(
            f"Presupuesto de comisiones agotado: quedan {budget.round_trips_remaining:.1f}"
            " operaciones completas. Operar ahora convierte el rendimiento esperado en"
            " comisión pagada."
        )
        d.allocation_mxn = _allocation(policy, investable, current_crypto_mxn, curve, tenor)
        d.headline = "Sin presupuesto de comisiones. Mantener posición actual."
        return d

    # ---------- 8. Banda de no-operación ----------
    drift = abs(current_crypto_mxn - target_sleeve)
    band = max(target_sleeve * REBALANCE_BAND_RELATIVE, budget.cost_per_round_trip_mxn * 10.0)
    d.allocation_mxn = _allocation(policy, investable, target_sleeve, curve, tenor)

    if drift <= band:
        d.action = "HOLD_NO_ACTION"
        d.headline = (
            f"Sin acción. Desviación de {drift:,.0f} MXN dentro de la banda de"
            f" {band:,.0f} MXN; rebalancear cuesta más de lo que corrige."
        )
        return d

    d.action = "ALLOCATE_TO_CRYPTO" if target_sleeve > current_crypto_mxn else "REDUCE_CRYPTO"
    delta = target_sleeve - current_crypto_mxn
    d.headline = (
        f"{'Aumentar' if delta > 0 else 'Reducir'} sleeve cripto en {abs(delta):,.0f} MXN"
        f" (objetivo {target_sleeve:,.0f} MXN, {sizing.weight:.1%} del invertible)."
        f" Costo estimado {abs(delta) * budget.cost_per_round_trip_pct / 2:,.0f} MXN."
    )
    return d


def _allocation(
    policy: Policy, investable: float, sleeve: float, curve: dict[int, float], tenor: int
) -> dict[str, float]:
    # El sleeve nunca puede exceder lo invertible: en la rama de presupuesto
    # agotado se pasa la posición ACTUAL, que puede ser mayor. Sin este clamp
    # la asignación sumaba 51,000 sobre un capital de 50,000 y rompía el
    # contrato del snapshot que consume Android.
    sleeve = max(min(sleeve, investable), 0.0)
    out: dict[str, float] = {"reserva_liquidez": policy.portfolio.liquidity_reserve_mxn}
    for sym, w in zip(policy.universe.crypto_symbols, policy.universe.crypto_weights):
        out[sym] = round(sleeve * w, 2)
    out[f"CETES_{tenor}d"] = round(investable - sleeve, 2)
    return out
