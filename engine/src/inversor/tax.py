"""
Aritmética fiscal mexicana. Aquí vive la parte que casi todas las apps de
inversión ignoran y que a capital chico invierte el resultado.

Dos asimetrías que importan:

1. CETES: se acumula el interés REAL (nominal menos inflación), no el nominal.
   Con CETES a 7.01% e inflación a 4%, el interés gravable es ~3%, no 7%.
   Eso hace a CETES más atractivo de lo que sugiere la cuenta ingenua.

2. Cripto: la ganancia por enajenación de bienes muebles tiene exención anual
   de 3 x UMA (~128,383.92 MXN en 2026). Con capital < 50,000 MXN es
   aritméticamente imposible superarla. A esa escala, la ganancia cripto es
   ISR-exenta y el interés de CETES no lo es.

   ⚠️ ADVERTENCIA: la aplicabilidad de esa exención a activos virtuales NO está
   confirmada en criterio publicado del SAT. Está codificada como supuesto
   explícito y auditable, no como hecho. Verifícalo con tu contador.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import TaxPolicy


@dataclass(frozen=True)
class NetYield:
    nominal_rate: float
    inflation_rate: float
    real_rate_pretax: float
    taxable_real_rate: float
    isr_on_real: float
    net_nominal_rate: float
    net_real_rate: float
    retencion_provisional: float
    assumptions: tuple[str, ...]


def real_rate(nominal: float, inflation: float) -> float:
    """Fisher exacto. Correcto como ECONOMÍA (rendimiento real de verdad)."""
    return (1.0 + nominal) / (1.0 + inflation) - 1.0


def fiscal_real_interest(nominal: float, inflation: float) -> float:
    """
    Base gravable según LISR art. 134: interés nominal MENOS el ajuste por
    inflación sobre el principal. Es una RESTA, no Fisher.

    No es un detalle cosmético: Fisher da 3.77% donde la ley da 3.89% con
    CETES 7.01% e inflación 3.12%. Usar Fisher aquí subestima el ISR.
    Fisher se queda para reportar el rendimiento real de verdad; la resta
    manda para calcular impuesto.
    """
    return nominal - inflation


def annualized_to_period(annual_rate: float, days: int, basis: int = 365) -> float:
    """
    Convierte una tasa anualizada al periodo real de tenencia.

    Esto existe porque el error más caro de este tipo de herramienta es
    comparar una tasa anual contra un rendimiento de 28 días. CETES a 28 días
    al 6.17% NO paga 6.17% en 28 días: paga ~0.47%.
    """
    if days <= 0:
        raise ValueError("days debe ser positivo")
    return (1.0 + annual_rate) ** (days / basis) - 1.0


def cetes_net_yield(nominal: float, inflation: float, tax: TaxPolicy) -> NetYield:
    """
    Rendimiento CETES neto de ISR sobre interés real.

    El ISR se calcula sobre el interés real (LISR art. 134). La retención del
    0.90% sobre capital es PROVISIONAL: se acredita en la anual. Se reporta
    aparte para que veas el flujo de caja, pero no se resta dos veces del
    rendimiento neto devengado.
    """
    r_real = real_rate(nominal, inflation)                 # economía
    taxable = max(fiscal_real_interest(nominal, inflation), 0.0)  # base gravable, LISR 134
    isr = taxable * tax.marginal_isr_rate
    net_nominal = nominal - isr
    net_real = real_rate(net_nominal, inflation)
    return NetYield(
        nominal_rate=nominal,
        inflation_rate=inflation,
        real_rate_pretax=r_real,
        taxable_real_rate=taxable,
        isr_on_real=isr,
        net_nominal_rate=net_nominal,
        net_real_rate=net_real,
        retencion_provisional=tax.retencion_provisional_anual,
        assumptions=(
            f"ISR marginal supuesto: {tax.marginal_isr_rate:.0%} (confirmar con contador)",
            "Base gravable = interés nominal − inflación (resta, LISR art. 134),"
            " no la relación de Fisher",
            f"Retención provisional {tax.retencion_provisional_anual:.2%} sobre el capital"
            " (LIF 2026 art. 24; subió desde 0.50% en 2025). Es acreditable en la anual,"
            " por eso no se resta del rendimiento devengado.",
        ),
    )


def crypto_effective_isr_rate(expected_gain_mxn: float, tax: TaxPolicy) -> tuple[float, str]:
    """
    Tasa efectiva de ISR sobre una ganancia cripto esperada, considerando la
    exención anual restante.

    Devuelve (tasa_efectiva, explicación).
    """
    remaining = max(
        tax.exencion_anual_bienes_muebles_mxn - tax.ganancias_cripto_ytd_mxn, 0.0
    )
    if expected_gain_mxn <= 0:
        return 0.0, "Sin ganancia esperada; no hay ISR."
    if expected_gain_mxn <= remaining:
        return 0.0, (
            f"Ganancia esperada ({expected_gain_mxn:,.0f} MXN) por debajo de la exención"
            f" anual restante ({remaining:,.0f} MXN). ISR efectivo 0%."
            " SUPUESTO NO CONFIRMADO: exención 3xUMA aplicable a activos virtuales."
        )
    taxable = expected_gain_mxn - remaining
    effective = (taxable * tax.marginal_isr_rate) / expected_gain_mxn
    return effective, (
        f"Exención restante {remaining:,.0f} MXN consumida."
        f" {taxable:,.0f} MXN gravables a tasa marginal {tax.marginal_isr_rate:.0%}."
    )


def hurdle_rate(
    cetes_nominal: float,
    inflation: float,
    tax: TaxPolicy,
    required_risk_premium: float,
) -> tuple[float, NetYield]:
    """
    El número contra el que se mide todo.

    hurdle = rendimiento CETES neto de ISR + prima de riesgo exigida.

    Cualquier estrategia alternativa debe superar esto NETA de comisiones,
    NETA de su propio ISR y expresada en MXN (incluyendo el efecto cambiario).
    """
    ny = cetes_net_yield(cetes_nominal, inflation, tax)
    return ny.net_nominal_rate + required_risk_premium, ny
