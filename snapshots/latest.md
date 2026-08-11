# Aumentar sleeve cripto

**Aumentar sleeve cripto en 1,440 MXN (objetivo 1,440 MXN, 3.2% del invertible). Costo estimado 2 MXN.**

_Generado: 2026-08-11T20:45:21.765273+00:00 · schema 3.1.0_

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

## Próximos eventos

| Fecha | Evento | Verificado |
|---|---|---|
| 2026-08-11 | Subasta primaria de CETES | derivado |
| 2026-08-12 | Publicación de CPI de EE. UU. | ✓ |
| 2026-08-18 | Subasta primaria de CETES | derivado |
| 2026-08-25 | Subasta primaria de CETES | derivado |
| 2026-09-01 | Subasta primaria de CETES | derivado |
| 2026-09-08 | Subasta primaria de CETES | derivado |
| 2026-09-09 | Publicación de INPC (INEGI) | derivado |
| 2026-09-11 | Publicación de CPI de EE. UU. | ✓ |
| 2026-09-15 | Reunión del FOMC | ✓ |
| 2026-09-15 | Subasta primaria de CETES | derivado |
| 2026-09-22 | Subasta primaria de CETES | derivado |
| 2026-09-24 | Decisión de política monetaria de Banxico | derivado |
| 2026-09-29 | Subasta primaria de CETES | derivado |
| 2026-10-06 | Subasta primaria de CETES | derivado |
| 2026-10-09 | Publicación de INPC (INEGI) | derivado |

### Si Banxico mueve la tasa (escenarios declarados, no pronósticos)

| Movimiento | Hurdle anualizado | Sleeve objetivo | Δ sleeve | Restricción |
|---|---:|---:|---:|---|
| -50 pb | 10.49% | 0 MXN | +0 | below_floor |
| -25 pb | 10.67% | 0 MXN | +0 | below_floor |
| +0 pb | 10.84% | 0 MXN | +0 | below_floor |
| +25 pb | 11.02% | 0 MXN | +0 | below_floor |

_El sizing de escenarios suma el costo de oportunidad de CETES al presupuesto de caída: es igual o MÁS estricto que el sizing del día. `below_floor` significa que el sleeve resultante queda bajo el piso operable y se va a cero._

## Razonamiento
- Hurdle: CETES 364d al 7.01% nominal → 5.84% neto de ISR (2.64% real). Más prima de riesgo de 5.00% = 10.84% anualizado, equivalente a 10.81% en 364 días.
- Vol realizada anualizada: 31.2%.
- Restricción vol-target (8.0% objetivo): 25.6%.
- Restricción presupuesto de caída (8.0% tolerable / 75% caída supuesta del activo): 10.7%.
- Tope duro: 20.0%.
- Restricción que manda: multiplicador(0.30).
- Escalado por multiplicador (régimen y señales, el que más apriete): x0.30.
- Fear & Greed en 29 (miedo, ≤ 40): tamaño x0.75.
- DVOL en 35.9: por debajo de 65, sin recorte.
- Volumen de noticias: fuente apagada por bandera (GDELT pendiente de estabilizarse). No cuenta como ceguera ni como calma: no opina.
- Sin rupturas regulatorias en 442 notas revisadas.
- 1 fuente no disponible (vix: Falta FRED_API_KEY (gratuita en https://fredaccount.stlouisfed.org/apikeys)): sin recorte todavía, los demás indicadores cubren el mismo régimen.
- Multiplicador de señales: 0.75 (mínimo de 2 recortes; acotado a [0.00, 1.00] por construcción, nunca amplifica).
- Banxico decide el 2026-09-24. Si recorta 50 pb, el hurdle anualizado baja de 10.84% a 10.49% y el sleeve objetivo pasa a 0 MXN (+0). Escenario declarado con la curva de hoy, no pronóstico.
- Costo por round-trip: 0.300% del monto rotado (0.100% comisión + 0.050% slippage, x2 lados).
- Presupuesto anual: 7 MXN (0.50% del sleeve de 1,440 MXN).
- Operaciones completas permitidas al año: 1.7.
- Un movimiento de precio menor al breakeven deja la operación en pérdida incluso si la dirección fue correcta.
- Para que el sleeve cripto haya valido la pena frente a CETES, tiene que rendir al menos 11.11% EN PESOS en 364 días. Ese rendimiento en pesos es rendimiento en dólares MÁS movimiento del tipo de cambio.
- Ganancia esperada (156 MXN) por debajo de la exención anual restante (128,384 MXN). ISR efectivo 0%. SUPUESTO NO CONFIRMADO: exención 3xUMA aplicable a activos virtuales.

## Advertencias
- ⚠️ Señales — fuente no disponible: vix: Falta FRED_API_KEY (gratuita en https://fredaccount.stlouisfed.org/apikeys). Se omite FRED; su ausencia se reporta, no se sustituye por un default.
- ⚠️ Señales — fuente no disponible: vix: sin dato.
- ⚠️ Sleeve de 1,440 MXN: aun con cripto +50%, el impacto en el portafolio total es +1.44%. Es ruido. Considera no tener la posición y ahorrarte el trabajo operativo y fiscal.
- ⚠️ Tienes ingresos y gastos en MXN. Una posición cripto es una posición larga en USD sin cobertura. A tu tamaño de cuenta, la volatilidad del tipo de cambio es comparable al alfa que puedes esperar.

---

_Este sistema no pronostica precios. Dimensiona riesgo, impone un techo de comisiones y compara contra CETES neto de impuestos. Uso personal. No es asesoría en inversiones._