# Guía de operación — inversor-min

Cómo funciona el sistema, cómo leer la app, y qué hacer (y qué no) cuando
llega un aviso. Esta guía no da consejos de inversión: documenta la
herramienta que tú decidiste construir y las reglas que tú le pusiste.

---

## 1. Qué es esto, en un párrafo

Cada día hábil a las **14:00 (CDMX)**, un robot en GitHub Actions descarga
datos públicos —tasas de Banxico, precios de BTC/ETH, indicadores de estrés,
noticias y el Diario Oficial—, calcula **cuánto tendría que rendir el sleeve
cripto para ganarle a CETES neto de impuestos** (el *hurdle*), dimensiona
cuánto riesgo cabe en tu presupuesto de pérdida, y publica UNA decisión con
su razonamiento completo en `snapshots/`. La app del teléfono la muestra.
ntfy te avisa **sólo si la decisión cambió**. El sistema **jamás ejecuta
órdenes**: mover dinero siempre es un acto manual tuyo.

Las tres salidas posibles, de más a menos frecuente:

| Salida | Qué significa | Qué haces |
|---|---|---|
| **Silencio** | La decisión no cambió | Nada. Es el sistema funcionando |
| **Aviso sin orden** | Cambió el contexto (régimen, hurdle, bloqueo) | Leerlo. No operar |
| **Aviso CON orden ejecutable** | La *acción* del día cambió y mueve dinero | El procedimiento de §4 |

---

## 2. El ciclo diario (sin que hagas nada)

1. **14:00 CDMX, L–V**: corre el cron (`decision-diaria` en Actions; a veces
   con 30–60 min de retraso, es normal en GitHub).
2. Verifica los títulos de las series de Banxico contra el catálogo
   (`verify-series`): si Banxico renombró algo, ese día NO se publica
   decisión y el job sale rojo.
3. Corre el motor y commitea `snapshots/AAAA-MM-DD.json` + `latest.json` +
   los archivos de avisos. Ese historial es el **log walk-forward**: la única
   forma de saber, con el tiempo, si esto le ganó a CETES.
4. Si hubo avisos, los manda a tu topic de **ntfy**.

Un día **bloqueado** (`BLOCKED_*`) también se publica: el log debe mostrar
los días en que el sistema dijo "no sé" o "no".

---

## 3. Cómo leer la app, pantalla por pantalla

### Hoy
- **El chip de acción** es la decisión: azul = quédate en CETES, verde =
  aumentar sleeve, ámbar = reducir, rojo = bloqueado.
- **"¿Mueve la aguja?"** — si dice **INMATERIAL** en ámbar, esa es la
  respuesta del día: el sleeve es tan chico que ni un +50% de cripto cambia
  tu año, mientras CETES te paga ~2,500 MXN netos sin volatilidad. La app lo
  pone arriba de todo a propósito.
- **Las dos tasas del hurdle no son intercambiables**: el *anualizado* es
  una tasa por año; el de *tu horizonte* es lo que cripto tiene que rendir
  en esos días. Para decidir, mira siempre el de tu horizonte.

### Por qué
El razonamiento completo del motor, sin resumir: hurdle paso a paso (con la
aritmética fiscal de LISR), señales de estrés (Fear & Greed, DVOL, VIX),
noticias revisadas, eventos próximos con escenarios de Banxico, y la
sensibilidad al tipo de cambio — recuerda que un sleeve cripto es una
posición larga en dólares sin cobertura.

### Historial
El log walk-forward, día por día. Es el registro con el que la rutina del
**9 de octubre de 2026** contestará la única pregunta que importa: ¿le ganó
a CETES, neto de todo?

### Avisos
Los avisos de la última corrida. La **banda roja "CARGA ORDEN EJECUTABLE"**
marca los únicos avisos que cuestan dinero si los sigues — hay máximo ~1.7
de esos al año, porque el presupuesto de avisos se deriva del de comisiones.
Los **Suprimidos** (colapsados) son lo que el anti-spam silenció y por qué:
ver lo que NO se te avisó es parte de poder confiar en el silencio.

### Banners
- **"Datos guardados del…"**: estás viendo caché; se refresca solo.
- **Banner rojo "DATOS RANCIOS"**: no tomes decisiones con esos números.
- **"Actualiza la app"**: el esquema cambió de mayor; reinstala el APK.

---

## 4. El procedimiento cuando llega un aviso con orden

El sistema no ejecuta. Si un día decides seguir una orden, el procedimiento
es éste, en orden, y cualquier "no" lo detiene:

1. **Abre la app y lee el aviso completo** — el razonamiento Y las líneas de
   **INVALIDACIÓN** que trae. Cada aviso lista las condiciones bajo las que
   ya no es válido (el hurdle se movió, el presupuesto bajó, el veredicto es
   INMATERIAL). Si una se cumple, no hay orden.
2. **Verifica el presupuesto**: `Operaciones restantes ≥ 1.0` en la pantalla
   Hoy. Si no alcanza para la vuelta completa (entrar Y salir), no entres.
3. **Verifica materialidad**: si el veredicto es INMATERIAL, "no operar" es
   una respuesta correcta, no una omisión.
4. **Si decides ejecutar**: lo haces tú, a mano, en tu exchange, por el
   monto objetivo de la asignación (no más). El sistema nunca sabrá tu
   contraseña y así debe seguir.
5. **Después de ejecutar, actualiza las variables del repo** — este paso es
   el que mantiene al sistema honesto:

```bash
gh variable set HELD_MXN --repo alexgrangel/inversor-min --body "1440"
```

```bash
gh variable set FEES_YTD_MXN --repo alexgrangel/inversor-min --body "4.32"
```

   `HELD_MXN` = tu sleeve cripto real en MXN tras la operación.
   `FEES_YTD_MXN` = comisiones acumuladas del año (suma lo que pagaste).
   Y si **vendiste con ganancia**, registra la ganancia realizada del
   ejercicio (alimenta el cálculo de la exención fiscal):

```bash
gh variable set CRYPTO_GAINS_YTD_MXN --repo alexgrangel/inversor-min --body "0"
```

   Desde la corrida siguiente, el motor dimensiona sobre tu posición real y
   descuenta el presupuesto gastado. **Cada 1 de enero**, resetea
   `FEES_YTD_MXN` y `CRYPTO_GAINS_YTD_MXN` a 0.

**Bloqueos**: cualquier `BLOCKED_*` significa que ninguna orden derivada de
ese snapshot es válida. En particular, **ruptura estructural** (CNBV, SAT,
LISR) significa que lo que está en duda es el *modelo*, no el precio: eso se
resuelve leyendo la noticia y, si es fiscal, con tu contador — nunca
operando.

---

## 5. Cambiar la política (las reglas del juego)

Las decisiones de política son tuyas y se cambian **en frío**, editando
variables o código — nunca como reacción a una "oportunidad" (regla 8: las
señales sólo reducen o bloquean; regla 6: el sistema puede decirte que no).

- **Capital y reserva**: variables `CAPITAL_MXN` y `RESERVE_MXN` del repo
  (defaults: 50,000 / 5,000). ⚠️ *Privacidad*: el repo es público y el
  snapshot publica las asignaciones en MXN. Con los valores redondos de la
  política es un parámetro nominal; si pones tus números exactos, serán
  públicos.
- **Presupuesto de pérdida, vol target, topes**: `RiskPolicy` en
  `engine/src/inversor/config.py` (con comentario de fuente, regla 5).
- **Tu tasa marginal de ISR**: variable `ISR_MARGINAL` (default 0.30, es un
  placeholder — confírmala con tu contador; mueve el hurdle ~100 pb).
- **Horizonte**: `HORIZON_DAYS` (default 364; determina qué CETES es tu
  vara de medir).

Después de cambiar una variable, la siguiente corrida la usa sola. Si
cambias código: `pytest` en verde antes de pushear.

---

## 6. Lo que el sistema vigila solo (y lo que no puede)

**Vigila solo**: rancidez de cada serie según su calendario real; monotonía
de la curva de CETES; que los títulos de las series de Banxico sigan siendo
lo que creemos; caídas de venues (Kraken→Coinbase→Binance); fuentes de
noticias caídas (2+ ciegas = recorte automático de tamaño); rupturas
regulatorias en 400+ notas diarias del DOF, Expansión, El Financiero y
Bloomberg Línea; el presupuesto de comisiones; y su propio anti-spam.

**No puede vigilar**: (1) que `HELD_MXN` refleje tu posición real — eso es
tuyo tras cada operación; (2) la pregunta fiscal abierta de la **exención
3×UMA aplicada a cripto** — el SAT no ha publicado criterio; es la pregunta
para tu contador, y si la respuesta es "no aplica", el hurdle sube ~150 pb;
(3) las fechas de Banxico de 2027 en adelante — `events.py` avisará
`CALENDARIO_AGOTADO` cuando toque actualizarlas.

---

## 7. Si algo se ve mal

| Síntoma | Qué es | Qué hacer |
|---|---|---|
| Job rojo en Actions | El motor no pudo publicar (red, Banxico caído, título cambiado) | Ver el log del run; un día perdido no daña el log |
| Banner rojo en la app | Datos rancios reales | No operar; usualmente se cura solo al día siguiente |
| Aviso `OVERTRADING_DETECTED` | El sistema quiso avisarte más de lo que puedes pagar | Revisar la política, no operar |
| ntfy no llega | Suscripción o topic | Revisa la suscripción al topic en la app de ntfy |
| "Actualiza la app" | Subió el mayor del esquema | Recompilar e instalar el APK (README de android/) |

**Qué no tocar jamás**: `snapshots/` (historia inmutable, regla 3),
`notifications.json` (la memoria del anti-spam), y nada de force-push a
`main`. El workflow tiene guards que truenan si algo lo intenta.

---

## 8. Calendario

- **Cada día hábil, ~14:00–15:00 CDMX**: corrida y, si aplica, aviso.
- **9 de octubre de 2026, 16:00 CDMX**: la rutina del día 60 corre el
  análisis walk-forward (¿le ganó a CETES?) y deja el reporte en
  `docs/analisis-dia-60.md`. Sin optimizar parámetros: medir, no ajustar.
- **24-sep / 5-nov / 17-dic 2026**: decisiones de Banxico — la app ya trae
  los escenarios precalculados (qué pasa con tu hurdle a ±25/50 pb).
- **1 de enero**: resetear `FEES_YTD_MXN` y `CRYPTO_GAINS_YTD_MXN`.

---

*Uso personal. No es asesoría en inversiones. El sistema no pronostica
precios: dimensiona riesgo y compara contra el costo de oportunidad. Su
salida más frecuente y más valiosa es el silencio.*
