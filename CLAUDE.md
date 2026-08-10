# CLAUDE.md — reglas del repo

Léelo completo antes de escribir una línea. Estas reglas no son estilo, son la
diferencia entre una herramienta útil y una máquina de perder dinero despacio.

## Qué es esto

Motor de decisión de inversión personal para **una** persona, en México, con
capital menor a 50,000 MXN. Compara el costo de oportunidad libre de riesgo
(CETES, neto de ISR sobre interés real) contra un sleeve cripto dimensionado
por presupuesto de pérdida. Es **read-only**: nunca ejecuta órdenes.

Cliente Android que lee un JSON público. Sin backend, sin servidor, sin llaves.

## Las diez reglas

1. **Prohibido pronosticar rendimientos.** No hay modelos de precio, ni ML, ni
   "señales predictivas", ni sentiment. El sistema dimensiona riesgo e impone
   presupuestos. Si te encuentras escribiendo `predicted_return`, borra y
   replantea. La única predicción permitida es "la volatilidad reciente se
   parece a la volatilidad próxima", y aun esa se usa sólo para reducir tamaño.

2. **Cero llaves de API de exchange en cualquier parte del repo.** Ni en el
   engine, ni en Android, ni en secretos de CI. Sólo endpoints públicos de
   mercado. Un APK se descompila en dos minutos. Si alguien pide "agrégale
   ejecución automática", eso es otro repo, con otro modelo de amenaza.

3. **El `snapshots/` es sagrado.** Es el log walk-forward. Nunca reescribas un
   snapshot pasado, nunca hagas force-push a `main`, nunca hagas rebase de esa
   historia. Si el formato cambia, sube `SCHEMA_VERSION`; no reescribas lo viejo.

4. **Datos rancios bloquean, no degradan.** Si Banxico o Binance no responden o
   el dato tiene más días de los permitidos, la salida es
   `BLOCKED_STALE_DATA`. Nunca uses el último valor conocido en silencio.
   Nunca sustituyas un dato faltante por un default.

5. **Números inventados = bug crítico.** Ninguna tasa, comisión, tarifa fiscal o
   umbral se escribe a mano en el código. O viene de una API, o vive en
   `config.py` con comentario de fuente y marca de verificación pendiente.
   Los rangos de cordura en `sources/banxico.py` existen para que un ID de serie
   equivocado truene en vez de producir una recomendación sobre basura.

6. **Toda restricción se expresa como bloqueo duro, no como advertencia.**
   Presupuesto de comisiones agotado ⇒ `BLOCKED_FEE_BUDGET`, no un texto en gris.
   El sistema debe ser capaz de decirle que no a su dueño.

7. **La salida más valiosa es `STAY_IN_CETES`.** Si en una semana de pruebas el
   engine nunca recomienda quedarse en CETES, está roto. Revisa el hurdle.

8. **Las noticias sólo pueden REDUCIR el tamaño o BLOQUEAR. Nunca aumentarlo.**
   El combinador de `signals.py` devuelve un multiplicador acotado a [0, 1] y
   hay un test de propiedad que lo martillea con entradas adversariales para
   probar que ninguna puede sacar un valor mayor a 1.0. Esta asimetría no es
   una preferencia: es lo que separa esta herramienta de una máquina de
   sobreoperar. Una fuente caída **jamás** se lee como calma; se lee como
   ceguera, y la ceguera reduce el tamaño.

9. **No puedes ser avisado de actuar más veces de las que puedes pagar por
   actuar.** El presupuesto anual de notificaciones con orden ejecutable se
   DERIVA del presupuesto de comisiones (~1.7 operaciones al año), no se
   configura. Cualquier notificación que cargue una orden ejecutable se cuenta
   contra ese presupuesto, sin importar qué disparador la haya generado. Si el
   sistema quiere avisarte más seguido, la respuesta correcta es un aviso de
   `OVERTRADING_DETECTED` que te diga que revises la política, no que operes.

10. **Binance no es alcanzable desde CI.** Devuelve HTTP 451 desde IPs
    estadounidenses y los runners de GitHub Actions son estadounidenses. El
    orden de venues es Kraken → Coinbase → Binance, y Binance sólo sirve
    corriendo desde una máquina no estadounidense. El venue que sirvió cada
    precio va al snapshot: un cambio de fuente es una discontinuidad en los
    datos, no un detalle de infraestructura.

## Arquitectura

```
engine/          Python 3.11+, cero dependencias en runtime (sólo stdlib)
  sources/
    banxico.py       SIE API (requiere token): FIX, curva CETES, INPC
    market_data.py   Kraken → Coinbase → Binance. Sin llaves. Venue-neutral
    market_stress.py Fear & Greed, Deribit DVOL, FRED (VIX, dólar, 10y)
    news.py          GDELT, RSS mexicano, DOF vía SIDOF
  tax.py         LISR: ISR sobre interés REAL; exención 3xUMA en cripto
  costs.py       presupuesto anual de comisiones → round-trips permitidos
  risk.py        vol targeting ∩ presupuesto de caída ∩ tope duro
  regime.py      SMA200/SMA50/vol-percentil → multiplicador de tamaño (≤ 1.0)
  signals.py     combinador asimétrico: sólo reduce o bloquea (regla 8)
  events.py      calendario Banxico/FOMC/CPI + escenarios precalculados
  decide.py      la compuerta; emite una Decision con razonamiento explícito
  notify.py      cambios de estado → avisos, con presupuesto derivado (regla 9)
  notify_sinks.py  markdown + ntfy
  report.py      snapshot.json + markdown
.github/workflows/daily.yml   cron → corre engine → commitea snapshot
snapshots/       log walk-forward inmutable + latest.json + notifications.json
android/         Kotlin + Compose, read-only, sin backend
```

`snapshots/notifications.json` es append-only por la misma razón que los
snapshots: además de log, es la MEMORIA de cooldowns e histéresis entre
corridas del cron. Reescribirlo borra el estado del anti-spam y el sistema
vuelve a avisar de todo.

## Contrato engine → Android

`snapshots/latest.json` es la única interfaz. Reglas:

- Campos nuevos: permitidos sin subir versión mayor.
- Renombrar o quitar campos: sube `SCHEMA_VERSION` mayor y actualiza Android.
- Android debe manejar `schema_version` desconocido mostrando un aviso, nunca
  crasheando ni renderizando parcial en silencio.
- El JSON **no contiene datos personales**: sin saldos reales, sin cuentas, sin
  identificadores. Sólo tasas, pesos objetivo en MXN calculados sobre la política
  del repo, y razonamiento. Por eso el repo puede ser público.

## Estilo

- Python: stdlib. Si necesitas una dependencia, justifícala en el PR.
- Type hints en todo. `from __future__ import annotations` arriba.
- Nada de `try/except` que se traguen errores. Si algo falla, truena fuerte.
- Comentarios en español, en el punto donde una decisión de diseño no es obvia.
  No comentes lo que el código ya dice.
- Kotlin: Compose, sin RxJava, sin Dagger. Es una app de tres pantallas.

## Tests

- `pytest` sin red. Nunca escribas un test que pegue a una API.
- Todo bloqueo duro (comisiones, staleness, notional mínimo, tope de peso)
  necesita un test que demuestre que bloquea.
- Un test que sólo verifica que el código corre no cuenta.

## Lo que este repo NO va a hacer

No pidas ni implementes: ejecución automática de órdenes, apalancamiento,
futuros, perpetuos, copy-trading, alts fuera de BTC/ETH, backtests con
optimización de parámetros, ni distribución pública en Play Store. Cada una
cambia el modelo de riesgo, el modelo de amenaza o el perímetro regulatorio.
