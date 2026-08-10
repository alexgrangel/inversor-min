"""
Clasificación de régimen. Deliberadamente tonta.

Tres señales que llevan cuarenta años publicadas y sobreviven fuera de muestra
razonablemente bien. Nada optimizado, nada ajustado a la historia reciente.
Si le agregas parámetros, cada uno que añadas debe justificarse con un walk-forward,
no con un backtest.

La salida NO es un pronóstico de precio. Es un multiplicador de tamaño: en
régimen malo se toma menos riesgo, nunca más.
"""
from __future__ import annotations

from dataclasses import dataclass

from .risk import realized_vol

# Umbrales de régimen. Son juicios, no datos: por eso están nombrados y juntos
# en vez de dispersos como números mágicos. Cambiar cualquiera exige justificarlo
# con un walk-forward, no con un backtest. Ver CLAUDE.md regla 1.
VOL_STRESS_PERCENTILE = 0.90   # decil superior de vol de 2 años ⇒ estrés
MULT_STRESS = 0.25
MULT_RISK_ON = 1.00
MULT_NEUTRAL = 0.60
MULT_RISK_OFF = 0.30
DEEP_DRAWDOWN = -0.35          # caída desde máximo de 12m que fuerza recorte
MULT_DEEP_DRAWDOWN = 0.30


@dataclass(frozen=True)
class RegimeState:
    label: str
    size_multiplier: float
    price: float
    sma_200: float
    sma_50: float
    pct_from_200: float
    drawdown_from_1y_high: float
    vol_30d: float
    vol_percentile_2y: float
    signals: tuple[str, ...]


def _sma(closes: list[float], n: int) -> float:
    if len(closes) < n:
        raise ValueError(f"Se requieren {n} cierres, hay {len(closes)}.")
    return sum(closes[-n:]) / n


def _rolling_vol_series(closes: list[float], window: int = 30, step: int = 5) -> list[float]:
    out: list[float] = []
    i = window + 1
    while i <= len(closes):
        try:
            out.append(realized_vol(closes[:i], window=window))
        except ValueError:
            pass
        i += step
    return out


def classify(closes: list[float]) -> RegimeState:
    if len(closes) < 210:
        raise ValueError(
            f"Se requieren al menos 210 cierres diarios para clasificar régimen; hay {len(closes)}."
        )

    price = closes[-1]
    sma200 = _sma(closes, 200)
    sma50 = _sma(closes, 50)
    pct_from_200 = price / sma200 - 1.0

    lookback_1y = closes[-min(365, len(closes)):]
    dd_1y = price / max(lookback_1y) - 1.0

    vol30 = realized_vol(closes, window=30)
    vol_hist = _rolling_vol_series(closes[-min(730, len(closes)):])
    if len(vol_hist) >= 10:
        below = sum(1 for v in vol_hist if v <= vol30)
        vol_pct = below / len(vol_hist)
    else:
        vol_pct = 0.5

    signals: list[str] = [
        f"Precio {'arriba' if price > sma200 else 'abajo'} de la SMA200"
        f" ({pct_from_200:+.1%}).",
        f"SMA50 {'arriba' if sma50 > sma200 else 'abajo'} de SMA200.",
        f"Caída desde el máximo de 12 meses: {dd_1y:.1%}.",
        f"Vol 30d anualizada: {vol30:.1%} (percentil {vol_pct:.0%} de 2 años).",
    ]

    # Estrés manda sobre todo lo demás.
    if vol_pct >= VOL_STRESS_PERCENTILE:
        return RegimeState(
            "STRESS", MULT_STRESS, price, sma200, sma50, pct_from_200, dd_1y, vol30, vol_pct,
            tuple(signals + [
                f"Volatilidad en decil superior de 2 años: tamaño al {MULT_STRESS:.0%}."
            ]),
        )

    above_200 = price > sma200
    golden = sma50 > sma200

    if above_200 and golden:
        label, mult = "RISK_ON", MULT_RISK_ON
    elif above_200 or golden:
        label, mult = "NEUTRAL", MULT_NEUTRAL
    else:
        label, mult = "RISK_OFF", MULT_RISK_OFF

    if dd_1y <= DEEP_DRAWDOWN and not above_200:
        mult = min(mult, MULT_DEEP_DRAWDOWN)
        signals.append(
            f"Caída > {abs(DEEP_DRAWDOWN):.0%} y precio bajo SMA200:"
            f" tamaño limitado a {MULT_DEEP_DRAWDOWN:.0%}."
        )

    signals.append(f"Régimen {label}: multiplicador de tamaño {mult:.2f}.")
    return RegimeState(
        label, mult, price, sma200, sma50, pct_from_200, dd_1y, vol30, vol_pct, tuple(signals)
    )


def blended_multiplier(states: list[RegimeState], weights: list[float] | None = None) -> float:
    """
    Multiplicador combinado = el MÍNIMO de los activos del sleeve.

    Antes era min(promedio_ponderado, min*1.5, 1.0). Ese 1.5 no salía de
    ningún lado y el término que mandaba era justamente el 1.5×min: con BTC
    en NEUTRAL (0.60) y ETH en RISK_OFF (0.30), publicaba 0.45 — 50% más
    tamaño del que el activo estresado justifica. El docstring decía "se usa
    el mínimo" y el código hacía otra cosa.

    Un sleeve es una sola posición de riesgo. Si una de sus patas está en
    estrés, la posición entera baja.
    """
    if not states:
        return 0.0
    return min(s.size_multiplier for s in states)
