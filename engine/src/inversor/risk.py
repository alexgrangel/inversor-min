"""
Dimensionamiento por riesgo, no por convicción.

El tamaño de la posición cripto sale del mínimo de tres restricciones
independientes. La que más aprieta manda. Ninguna depende de pronosticar
el precio.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Sizing:
    weight: float
    weight_mxn: float
    binding_constraint: str
    vol_target_weight: float
    drawdown_budget_weight: float
    hard_cap_weight: float
    realized_vol_annual: float
    implied_portfolio_vol: float
    implied_worst_case_loss_mxn: float
    notes: tuple[str, ...]


def realized_vol(closes: list[float], window: int = 30, periods_per_year: int = 365) -> float:
    """Volatilidad realizada anualizada sobre retornos logarítmicos diarios."""
    if len(closes) < window + 1:
        raise ValueError(f"Se requieren al menos {window + 1} cierres, hay {len(closes)}.")
    rets = [
        math.log(closes[i] / closes[i - 1])
        for i in range(len(closes) - window, len(closes))
        if closes[i - 1] > 0
    ]
    n = len(rets)
    if n < 2:
        raise ValueError("Serie insuficiente para calcular volatilidad.")
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    return math.sqrt(var) * math.sqrt(periods_per_year)


def max_drawdown(closes: list[float]) -> float:
    peak, mdd = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        mdd = min(mdd, c / peak - 1.0)
    return mdd


def size_crypto_sleeve(
    investable_mxn: float,
    vol_annual: float,
    vol_target: float,
    max_dd_budget: float,
    assumed_asset_dd: float,
    hard_cap: float,
    floor: float,
    regime_multiplier: float = 1.0,
) -> Sizing:
    """
    Tres restricciones:
      1. Vol targeting:      w = vol_target / vol_realizada
      2. Presupuesto de DD:  w = drawdown_tolerable / drawdown_supuesto_del_activo
      3. Tope duro:          w <= hard_cap

    regime_multiplier escala hacia abajo en regímenes malos. Nunca escala
    hacia arriba por encima de 1.0: no se apuesta más porque las cosas se ven bien.
    """
    w_vol = vol_target / vol_annual if vol_annual > 0 else 0.0
    w_dd = max_dd_budget / assumed_asset_dd if assumed_asset_dd > 0 else 0.0

    candidates = {
        "vol_target": w_vol,
        "drawdown_budget": w_dd,
        "hard_cap": hard_cap,
    }
    binding = min(candidates, key=lambda k: candidates[k])
    base = min(candidates.values())
    mult = min(regime_multiplier, 1.0)
    w = base * mult

    # Si el multiplicador de régimen recortó más que la restricción "ganadora",
    # el que manda es el régimen. Reportar 'drawdown_budget' cuando en realidad
    # el tamaño lo fijó un multiplicador de 0.45 es mentirle al usuario sobre
    # por qué su posición es del tamaño que es.
    if mult < 1.0:
        binding = f"regime_multiplier({mult:.2f})"

    notes: list[str] = [
        f"Vol realizada anualizada: {vol_annual:.1%}.",
        f"Restricción vol-target ({vol_target:.1%} objetivo): {w_vol:.1%}.",
        f"Restricción presupuesto de caída ({max_dd_budget:.1%} tolerable /"
        f" {assumed_asset_dd:.0%} caída supuesta del activo): {w_dd:.1%}.",
        f"Tope duro: {hard_cap:.1%}.",
        f"Restricción que manda: {binding}.",
    ]

    if regime_multiplier < 1.0:
        notes.append(f"Escalado por régimen: x{regime_multiplier:.2f}.")

    if w < floor:
        notes.append(
            f"Peso resultante {w:.1%} por debajo del piso {floor:.1%}."
            " Posición demasiado chica para justificar el costo operativo: se lleva a 0%."
        )
        w = 0.0
        binding = "below_floor"

    w_mxn = investable_mxn * w
    return Sizing(
        weight=w,
        weight_mxn=w_mxn,
        binding_constraint=binding,
        vol_target_weight=w_vol,
        drawdown_budget_weight=w_dd,
        hard_cap_weight=hard_cap,
        realized_vol_annual=vol_annual,
        implied_portfolio_vol=w * vol_annual,
        implied_worst_case_loss_mxn=w_mxn * assumed_asset_dd,
        notes=tuple(notes),
    )
