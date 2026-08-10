# Aumentar sleeve cripto

**Aumentar sleeve cripto en 1,440 MXN (objetivo 1,440 MXN, 3.2% del invertible). Costo estimado 2 MXN.**

_Generado: 2026-08-10T20:43:23.136768+00:00 · schema 3.0.0_

## Costo de oportunidad

| Concepto | Valor |
|---|---|
| CETES 364d nominal (anual) | 7.01% |
| Inflación anual | 3.12% |
| Interés real (Fisher) | 3.77% |
| Base gravable LISR 134 (resta) | 3.89% |
| ISR sobre esa base | −1.17% |
| **CETES neto nominal (anual)** | **5.84%** |
| CETES neto real | 2.64% |
| Prima de riesgo exigida | 5.00% |
| **Hurdle anualizado** | **10.84%** |
| **Hurdle en tu horizonte (364d)** | **10.81%** |

## Asignación objetivo

| Instrumento | MXN |
|---|---:|
| reserva_liquidez | 5,000 |
| BTC | 1,080 |
| ETH | 360 |
| CETES_364d | 43,560 |

## Presupuesto de comisiones

- Operaciones completas permitidas al año: **1.7**
- Restantes: **1.7**
- Movimiento mínimo para no perder por comisiones: **0.30%**

## ¿Mueve la aguja?

Sleeve = **2.9%** del capital total · veredicto **INMATERIAL**

| Si cripto hace… | Impacto en el portafolio | En pesos |
|---|---:|---:|
| -50% | -1.44% | -720 MXN |
| -25% | -0.72% | -360 MXN |
| +25% | +0.72% | +360 MXN |
| +50% | +1.44% | +720 MXN |
| +100% | +2.88% | +1,440 MXN |

Contra eso: CETES te paga **2,545 MXN** al año, neto, sin volatilidad.

## Qué tan grande es la apuesta implícita

> Para que el sleeve cripto haya valido la pena frente a CETES, tiene que rendir al menos 11.11% EN PESOS en 364 días. Ese rendimiento en pesos es rendimiento en dólares MÁS movimiento del tipo de cambio.

### Sensibilidad al tipo de cambio

| Movimiento MXN | Rendimiento USD requerido |
|---|---:|
| -10% | 23.46% |
| -5% | 16.96% |
| +0% | 11.11% |
| +5% | 5.82% |
| +10% | 1.01% |

## Razonamiento
- Hurdle: CETES 364d al 7.01% nominal → 5.84% neto de ISR (2.64% real). Más prima de riesgo de 5.00% = 10.84% anualizado, equivalente a 10.81% en 364 días.
- Vol realizada anualizada: 31.0%.
- Restricción vol-target (8.0% objetivo): 25.8%.
- Restricción presupuesto de caída (8.0% tolerable / 75% caída supuesta del activo): 10.7%.
- Tope duro: 20.0%.
- Restricción que manda: regime_multiplier(0.30).
- Escalado por régimen: x0.30.
- Costo por round-trip: 0.300% del monto rotado (0.100% comisión + 0.050% slippage, x2 lados).
- Presupuesto anual: 7 MXN (0.50% del sleeve de 1,440 MXN).
- Operaciones completas permitidas al año: 1.7.
- Un movimiento de precio menor al breakeven deja la operación en pérdida incluso si la dirección fue correcta.
- Para que el sleeve cripto haya valido la pena frente a CETES, tiene que rendir al menos 11.11% EN PESOS en 364 días. Ese rendimiento en pesos es rendimiento en dólares MÁS movimiento del tipo de cambio.
- Ganancia esperada (156 MXN) por debajo de la exención anual restante (128,384 MXN). ISR efectivo 0%. SUPUESTO NO CONFIRMADO: exención 3xUMA aplicable a activos virtuales.

## Advertencias
- ⚠️ Sleeve de 1,440 MXN: aun con cripto +50%, el impacto en el portafolio total es +1.44%. Es ruido. Considera no tener la posición y ahorrarte el trabajo operativo y fiscal.
- ⚠️ Tienes ingresos y gastos en MXN. Una posición cripto es una posición larga en USD sin cobertura. A tu tamaño de cuenta, la volatilidad del tipo de cambio es comparable al alfa que puedes esperar.

---

_Este sistema no pronostica precios. Dimensiona riesgo, impone un techo de comisiones y compara contra CETES neto de impuestos. Uso personal. No es asesoría en inversiones._