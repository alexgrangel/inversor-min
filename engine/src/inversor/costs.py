"""
Presupuesto de comisiones. Este módulo es el que mata la idea original.

Con 50,000 MXN y comisión taker de 0.10% por lado, un round-trip cuesta 0.20%
(más slippage). Un presupuesto anual de comisiones del 0.50% del capital compra
exactamente 1.7 round-trips AL AÑO. No 1.7 al mes: al año.

Cualquier app que te sugiera operar más seguido que eso, a este tamaño de
cuenta, está transfiriendo tu capital al exchange. El engine lo bloquea en
duro en vez de recomendarlo con letras chiquitas.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import CostPolicy


@dataclass(frozen=True)
class CostBudget:
    capital_mxn: float
    annual_budget_mxn: float
    cost_per_round_trip_pct: float
    cost_per_round_trip_mxn: float
    max_round_trips_per_year: float
    round_trips_remaining: float
    fees_spent_ytd_mxn: float
    budget_exhausted: bool
    breakeven_move_pct: float
    notes: tuple[str, ...]


def compute_cost_budget(
    capital_mxn: float, sleeve_mxn: float, cost: CostPolicy
) -> CostBudget:
    """
    sleeve_mxn: el monto que realmente rota (el sleeve cripto), no el capital total.
    El presupuesto se define sobre el capital total porque es el denominador de
    tu rendimiento; el costo se paga sobre el monto que rota.
    """
    per_side = cost.taker_fee_pct + cost.slippage_pct
    rt_pct = 2.0 * per_side
    rt_mxn = sleeve_mxn * rt_pct

    # El presupuesto se define sobre el SLEEVE, no sobre el capital total.
    # Definirlo sobre el capital total era el bug: con sleeve de 2,160 MXN y
    # capital de 50,000, autorizaba 38.6 operaciones al año — 250 MXN de
    # comisiones sobre una posición cuyo exceso de rendimiento esperado sobre
    # CETES era de 247 MXN. Autorizaba gastar el 101% de la razón de tenerla.
    budget_mxn = sleeve_mxn * cost.annual_fee_budget_pct

    if rt_mxn <= 0:
        # Sleeve cero: no se inventa un notional de 1 peso para poder dividir.
        max_rt = 0.0
        rt_remaining = 0.0
        exhausted = cost.fees_spent_ytd_mxn > 0
    else:
        max_rt = budget_mxn / rt_mxn
        remaining_mxn = max(budget_mxn - cost.fees_spent_ytd_mxn, 0.0)
        rt_remaining = remaining_mxn / rt_mxn
        exhausted = rt_remaining < 1.0

    notes = (
        f"Costo por round-trip: {rt_pct:.3%} del monto rotado"
        f" ({cost.taker_fee_pct:.3%} comisión + {cost.slippage_pct:.3%} slippage, x2 lados).",
        f"Presupuesto anual: {budget_mxn:,.0f} MXN"
        f" ({cost.annual_fee_budget_pct:.2%} del sleeve de {sleeve_mxn:,.0f} MXN).",
        f"Operaciones completas permitidas al año: {max_rt:.1f}.",
        "Un movimiento de precio menor al breakeven deja la operación en pérdida"
        " incluso si la dirección fue correcta.",
    )

    return CostBudget(
        capital_mxn=capital_mxn,
        annual_budget_mxn=budget_mxn,
        cost_per_round_trip_pct=rt_pct,
        cost_per_round_trip_mxn=rt_mxn,
        max_round_trips_per_year=max_rt,
        round_trips_remaining=rt_remaining,
        fees_spent_ytd_mxn=cost.fees_spent_ytd_mxn,
        budget_exhausted=exhausted,
        breakeven_move_pct=rt_pct,
        notes=notes,
    )


def min_notional_ok(
    sleeve_mxn: float, usdmxn: float, weights: tuple[float, ...], cost: CostPolicy
) -> tuple[bool, str]:
    """
    ¿La pata MÁS CHICA supera el notional mínimo del venue?

    Revisar el promedio era el bug: con sleeve de 400 MXN repartido 75/25, el
    promedio da 11.67 USD (pasa) pero la pata de ETH da 5.83 USD y Binance la
    rechaza. Un bloqueo duro que aprobaba órdenes inejecutables.
    """
    if not weights:
        return False, "Sin patas que asignar."
    smallest_usd = (sleeve_mxn / usdmxn) * min(weights)
    ok = smallest_usd >= cost.min_notional_usd
    return ok, (
        f"Pata más chica: {smallest_usd:,.2f} USD vs mínimo"
        f" {cost.min_notional_usd:,.2f} USD ({'OK' if ok else 'POR DEBAJO DEL MÍNIMO'})."
    )
