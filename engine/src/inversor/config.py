"""
Política de inversión. TODO lo subjetivo vive aquí y en ningún otro lado.

Regla de diseño: el engine NO pronostica rendimientos. Dimensiona riesgo,
impone un presupuesto de comisiones y compara contra el costo de oportunidad
libre de riesgo (CETES) neto de impuestos. Si no libra el hurdle, la
recomendación es quedarse en CETES.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal

SCHEMA_VERSION = "3.0.0"
# 2.0.0: hurdle anualizado vs periodo (breaking)
# 3.0.0: activos canónicos BTC/ETH en vez de pares de Binance (breaking:
#        cambian las llaves de allocation_mxn), + frescura de precios


@dataclass(frozen=True)
class TaxPolicy:
    # Tarifa marginal de ISR que le aplica a Alex sobre intereses REALES
    # (LISR art. 134: personas físicas acumulan el interés real, no el nominal).
    # ⚠️ Confírmalo con tu contador. 0.30 es un placeholder razonable, no un dato.
    marginal_isr_rate: float = 0.30

    # Retención provisional sobre el CAPITAL invertido en instrumentos de deuda,
    # fijada anualmente en la Ley de Ingresos. 2026: 0.90% anual. [verificar en DOF]
    retencion_provisional_anual: float = 0.0090

    # Exención anual por enajenación de bienes muebles (LISR art. 93, frac. XIX b):
    # 3 x UMA anual. 2026 ≈ 128,383.92 MXN. Cripto se trata como bien mueble
    # intangible. ⚠️ La aplicabilidad de esta exención a cripto NO está resuelta
    # en criterio publicado por el SAT. Confírmalo con tu contador antes de
    # apoyarte en ella.
    exencion_anual_bienes_muebles_mxn: float = 128_383.92

    # Ganancias por enajenación de cripto ya realizadas en el ejercicio.
    # Se consume contra la exención.
    ganancias_cripto_ytd_mxn: float = 0.0


@dataclass(frozen=True)
class RiskPolicy:
    # Máxima caída tolerable del PORTAFOLIO TOTAL atribuible al sleeve cripto.
    # Este es el número que realmente decide tu asignación. Elígelo pensando
    # en pesos perdidos, no en porcentajes.
    max_portfolio_drawdown_from_crypto: float = 0.08  # 8%

    # Drawdown histórico de referencia del activo cripto en un ciclo malo.
    # BTC ha hecho -75%+ más de una vez. No lo bajes por optimismo.
    assumed_crypto_max_drawdown: float = 0.75

    # Objetivo de volatilidad anualizada aportada por el sleeve cripto.
    crypto_vol_target: float = 0.08  # 8%

    # Techo duro. Ninguna combinación de señales puede superarlo.
    max_crypto_weight: float = 0.20

    # Piso: por debajo de esto no vale la pena tener la posición (ruido operativo).
    min_crypto_weight: float = 0.03


@dataclass(frozen=True)
class CostPolicy:
    # Presupuesto anual de comisiones como % del capital total.
    # Este número es el que mata al trading activo con capital chico.
    annual_fee_budget_pct: float = 0.0050  # 0.50%

    # Comisión taker del venue (Binance spot: 0.10%, ~0.075% pagando con BNB).
    taker_fee_pct: float = 0.0010

    # Spread efectivo estimado + slippage por lado.
    slippage_pct: float = 0.0005

    # Notional mínimo del venue en USD (filtro MIN_NOTIONAL de Binance).
    min_notional_usd: float = 10.0

    # Comisiones ya gastadas en el ejercicio (MXN). Lo actualiza el usuario.
    fees_spent_ytd_mxn: float = 0.0


@dataclass(frozen=True)
class Portfolio:
    total_capital_mxn: float = 50_000.0
    # Horizonte en días. Determina qué punto de la curva CETES es el hurdle real.
    horizon_days: int = 364
    # Reserva de liquidez que nunca se invierte.
    liquidity_reserve_mxn: float = 5_000.0


@dataclass(frozen=True)
class Universe:
    # Activos CANÓNICOS, no pares de un exchange. Cada venue traduce en
    # sources/market_data.py. Antes decía "BTCUSDT" —un par de Binance— y el
    # snapshot publicaba ese nombre aunque el precio viniera de Kraken.
    # Solo activos con profundidad real y historia larga. Nada de alts.
    crypto_symbols: tuple[str, ...] = ("BTC", "ETH")
    # Pesos relativos dentro del sleeve cripto (suman 1.0).
    crypto_weights: tuple[float, ...] = (0.75, 0.25)

    # Orden de venues para datos de mercado. Kraken primero porque devuelve
    # 720 velas en una petición; Binance al final porque devuelve 451 desde
    # las IPs estadounidenses de GitHub Actions.
    venue_order: tuple[str, ...] = ("kraken", "coinbase", "binance")


@dataclass(frozen=True)
class Policy:
    portfolio: Portfolio = field(default_factory=Portfolio)
    tax: TaxPolicy = field(default_factory=TaxPolicy)
    risk: RiskPolicy = field(default_factory=RiskPolicy)
    cost: CostPolicy = field(default_factory=CostPolicy)
    universe: Universe = field(default_factory=Universe)

    # Prima de riesgo exigida por encima del hurdle CETES para justificar
    # tomar volatilidad de ~45% anual y riesgo cambiario sin cobertura.
    # Si no exiges prima, estás comprando volatilidad gratis.
    required_risk_premium: float = 0.0500  # 500 pb

    # Días máximos de antigüedad de un dato antes de marcarlo stale.
    max_staleness_days: int = 5

    def to_dict(self) -> dict:
        return asdict(self)


Regime = Literal["RISK_ON", "NEUTRAL", "RISK_OFF", "STRESS"]
Action = Literal[
    "STAY_IN_CETES",
    "ALLOCATE_TO_CRYPTO",
    "REDUCE_CRYPTO",
    "HOLD_NO_ACTION",
    "BLOCKED_FEE_BUDGET",
    "BLOCKED_STALE_DATA",
    "BLOCKED_BELOW_MIN_NOTIONAL",
]
