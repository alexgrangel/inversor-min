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

SCHEMA_VERSION = "3.1.0"
# 2.0.0: hurdle anualizado vs periodo (breaking)
# 3.0.0: activos canónicos BTC/ETH en vez de pares de Binance (breaking:
#        cambian las llaves de allocation_mxn), + frescura de precios
# 3.1.0: campos ADITIVOS `signals` y `eventos` (señales de estrés/noticias y
#        calendario con escenarios de Banxico). Mismo mayor: los snapshots
#        3.0.0 siguen siendo comparables — los campos nuevos rehidratan con
#        sus defaults.


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
class SignalsPolicy:
    """
    Qué fuentes de señales se consultan. Las señales sólo pueden REDUCIR el
    tamaño o BLOQUEAR (regla 8); estas banderas deciden a quién se le pregunta.
    Una fuente APAGADA no cuenta para el recorte por ceguera — apagada no es
    caída — pero jamás se lee como calma: simplemente no opina.
    """
    # Apagado maestro de la capa de señales (diagnóstico/emergencia).
    enabled: bool = True

    # GDELT queda FUERA del set por medición, no por accidente (Prompt 6,
    # 11-ago-2026): 8 de 9 peticiones inutilizables desde IP residencial con
    # espaciado de 12-20 s — siete 429 y un 200 cuyo cuerpo era un error de
    # sintaxis; un solo éxito real. Su propio mensaje de límite dice "una cada
    # 5 segundos" y aun así estrangula: el límite real es un presupuesto opaco
    # compartido. Desde los runners de GitHub (IPs compartidas) sería peor.
    # La respuesta correcta es sacarlo del set, no aflojar el umbral. Apagada
    # ≠ caída: no cuenta para el recorte por ceguera.
    gdelt_enabled: bool = False

    # Consulta de GDELT si algún día se reactiva. Los OR EXIGEN paréntesis:
    # sin ellos la API devuelve 200 con el error "Queries containing OR'd
    # terms must be surrounded by ()" como cuerpo (medido 11-ago-2026).
    gdelt_consulta: str = "(bitcoin OR ethereum OR criptomonedas)"

    # SIDOF arreglado (Prompt 6, 11-ago-2026): el repo le pegaba al JSON de
    # EJEMPLO de la página de datos abiertos; el servicio real está documentado
    # en los PDF de esa misma página y verificado en vivo (141 notas con
    # título de la edición del 11-ago). Ver sources/news.py.
    dof_enabled: bool = True


@dataclass(frozen=True)
class Policy:
    portfolio: Portfolio = field(default_factory=Portfolio)
    tax: TaxPolicy = field(default_factory=TaxPolicy)
    risk: RiskPolicy = field(default_factory=RiskPolicy)
    cost: CostPolicy = field(default_factory=CostPolicy)
    universe: Universe = field(default_factory=Universe)
    signals: SignalsPolicy = field(default_factory=SignalsPolicy)

    # Prima de riesgo exigida por encima del hurdle CETES para justificar
    # tomar volatilidad de ~45% anual y riesgo cambiario sin cobertura.
    # Si no exiges prima, estás comprando volatilidad gratis.
    required_risk_premium: float = 0.0500  # 500 pb

    # Días máximos de antigüedad de un dato antes de marcarlo stale, para
    # series DIARIAS (FIX, tasa objetivo, precios cripto). 5 tolera el peor
    # puente bancario normal; una serie diaria con 6+ días es un problema real.
    max_staleness_days: int = 5

    # Límites por serie para lo que NO publica diario. Un límite uniforme de 5
    # bloqueaba por diseño: la primera corrida real (10-ago-2026, lunes)
    # bloqueó con CETES a 6 días —la subasta es SEMANAL, martes 4-ago— y con
    # inpc_anual a 40 días —la inflación anual es MENSUAL, fechada al día 1
    # del mes de referencia. Regla 4 intacta: rancio de verdad sigue
    # bloqueando; esto sólo define "rancio" según el calendario real de cada
    # fuente.
    staleness_days_by_key: dict[str, int] = field(default_factory=lambda: {
        # Subasta semanal de CETES (martes, serie fechada a la subasta): el
        # dato vigente llega a 7 días el martes siguiente si el cron (14:00
        # CDMX) corre antes de los resultados (~13:30, sin garantía). 9 da
        # margen de un feriado que mueva la subasta; una subasta perdida
        # (13+ días) bloquea. Fuente: calendario de subastas de valores
        # gubernamentales de Banxico; dato del 4-ago verificado 10-ago-2026.
        "cetes_28": 9,
        "cetes_91": 9,
        "cetes_182": 9,
        "cetes_364": 9,
        # SP30578 es mensual y viene fechada al día 1 del mes de REFERENCIA;
        # INEGI publica el INPC de un mes ~el día 9 del mes siguiente. Peor
        # caso normal: la víspera de la publicación, el dato vigente (día 1
        # del mes anterior) tiene ~69-70 días. 75 tolera esa aritmética más
        # un retraso corto; un mes de publicación perdido (~100) bloquea.
        # Fuente: calendario de difusión del INEGI; dato del 01-jul con 40
        # días verificado 10-ago-2026.
        "inpc_anual": 75,
    })

    def staleness_limit(self, key: str) -> int:
        return self.staleness_days_by_key.get(key, self.max_staleness_days)

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
    # Una coincidencia con la lista curada de rupturas regulatorias (CNBV,
    # SAT, LISR 93/134, LIF) invalida el MODELO, no el precio. Exige revisión
    # humana; ningún multiplicador lo resuelve (regla 8).
    "BLOCKED_STRUCTURAL_BREAK",
]
