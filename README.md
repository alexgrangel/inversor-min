# inversor-min

Motor de decisión de inversión personal. Compara el costo de oportunidad libre
de riesgo en México (CETES, neto de ISR sobre interés real) contra un sleeve
cripto dimensionado por presupuesto de pérdida. **Read-only**: nunca ejecuta
órdenes, nunca toca una llave de API de exchange.

Uso personal. **No es asesoría en inversiones.**

## Por qué existe

Con capital menor a 50,000 MXN, el rendimiento no lo determina *qué* compras.
Lo determinan tres cosas que casi ninguna app te dice:

1. **El drag de comisiones.** 0.10% por lado en Binance más slippage = 0.30% por
   operación completa. Con un presupuesto de comisiones del 0.50% del monto que
   rota, eso compra **1.7 operaciones al año**. No al mes: al año.
2. **La aritmética fiscal mexicana.** El ISR sobre CETES se paga sobre el interés
   *real* (LISR art. 134), no el nominal — con CETES 7.01% e inflación 3.12%, la
   base gravable es 3.89%, no 7.01%. Y la ganancia cripto por enajenación de
   bienes muebles tiene exención anual de 3×UMA (128,383.92 MXN en 2026), que a
   este tamaño de cuenta es imposible superar.
3. **El tipo de cambio.** Ganas y gastas en pesos. Cripto es una posición larga en
   dólares sin cobertura. Con el peso en 17.14 y apreciándose, un año bueno de
   BTC en dólares puede ser un año mediocre en pesos.

El engine calcula las tres y responde una sola pregunta: **¿mover pesos fuera de
CETES supera el hurdle?** La respuesta más frecuente, y la más valiosa, es que no.

## Lo que NO hace

No pronostica precios. No usa ML, sentiment ni "señales predictivas". No opera.
No apalanca. No toca futuros ni perpetuos. No sale de BTC/ETH. No se publica en
Play Store. Cada una de esas cosas cambia el modelo de riesgo o el perímetro
regulatorio; ver `CLAUDE.md`.

## Arranque rápido

```bash
# 1. Token gratuito de Banxico
open https://www.banxico.org.mx/SieAPIRest/service/v1/token
export BANXICO_TOKEN=...

# 2. VERIFICA LOS IDs DE SERIE ANTES DE CONFIAR EN UN SOLO NÚMERO
cd engine && python -m inversor verify-series

# 3. Tests (sin red)
python -m pytest -q

# 4. Corrida sin escribir nada
python -m inversor run --capital 50000 --horizon 364 --dry-run

# 5. Ver la salida sin token ni red
PYTHONPATH=src python -m inversor.scripts.demo_offline
```

## Arquitectura

```
GitHub Actions (cron, gratis)
   └─ engine/  Python 3.11+, stdlib pura, cero dependencias en runtime
        ├─ Banxico SIE API  (FIX, curva CETES, INPC, tasa objetivo)
        └─ Binance público  (klines diarias — sin autenticación)
   └─ commit → snapshots/YYYY-MM-DD.json   ← log walk-forward inmutable
                snapshots/latest.json      ← contrato para Android
   
Android (Kotlin + Compose)
   └─ GET raw.githubusercontent.com/.../snapshots/latest.json
      Sin backend. Sin login. Sin secretos. Sin permisos salvo INTERNET.
```

El snapshot **no contiene datos personales**: sólo tasas, pesos objetivo y
razonamiento. Por eso el repo puede ser público y la app no necesita autenticarse.

`snapshots/` es el punto entero del proyecto. Cada corrida queda committeada con
timestamp inmutable. En seis meses ese historial es lo único que puede contestar
si el sistema le ganó a CETES fuera de muestra — sin él sólo vas a tener el
recuerdo de que funcionó.

## Estado de verificación de datos

Antes de poner un peso encima, ver la tabla de "hechos por verificar" en
`docs/PRD-y-plan.md`. Resumen de lo que **NO** está confirmado:

| Elemento | Estado | Consecuencia si está mal |
|---|---|---|
| IDs de serie CETES 91/182/364d | **sin verificar** | hurdle calculado sobre el plazo equivocado |
| ID de serie INPC general (`SP74665`) | **probablemente incorrecto**: parece ser inflación *no subyacente* | sesga interés real y por tanto el ISR |
| Exención 3×UMA aplicada a cripto | **sin criterio publicado del SAT** | ISR efectivo pasa de 0% a marginal |
| Tasa marginal de ISR (0.30) | **supuesto**, no dato | mueve el hurdle unos 100 pb |

Los rangos `SANITY` en `sources/banxico.py` atrapan basura, **no** atrapan lo
plausible-pero-equivocado. Una serie de CETES con el plazo incorrecto cae igual
dentro de [0.5, 30.0].

## Licencia

Privado. Uso personal.
