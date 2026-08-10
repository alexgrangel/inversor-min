# HANDOFF a Claude Code — inversor-min

Alex González Rangel · 10 de agosto de 2026 · esquema del snapshot **3.0.0**
Estado: **174 tests pasando**, motor verificado offline, cero corridas en vivo.

Este documento es la única cosa que necesitas leer para terminar la app. Los
prompts de la §5 están listos para pegar, en orden. No los reordenes: cada uno
desbloquea al siguiente, y los dos primeros existen porque hay dos cosas que
pueden hacer que todo lo demás sea inútil.

---

## 1. Qué es esto en una frase

Una app Android personal, de solo lectura, que cada día compara el costo de
oportunidad libre de riesgo en México (CETES neto de ISR sobre interés real)
contra un sleeve cripto dimensionado por presupuesto de pérdida, y **avisa solo
cuando la decisión cambia** — nunca cuando "hay una oportunidad".

## 2. Las dos peticiones que se rediseñaron, y por qué

Pediste avisos de "los mejores momentos para invertir" y noticias en tiempo real
como insumo. Ambas cosas están construidas, pero no como se pidieron. La razón
es un número: **tu presupuesto de comisiones permite 1.7 operaciones al año.**

### Notificaciones: cambios de estado, no oportunidades

Un sistema que te avisa del "mejor momento" es un generador de disparadores de
operación. Con 1.7 operaciones anuales de presupuesto, tiene 1.7 salidas útiles
al año. Todo lo demás es comisión pagada con pasos extra.

Lo que se construyó dispara sobre **transiciones**: la acción se voltea, entra o
sale un bloqueo, el régimen gira, el hurdle se mueve más de 50 pb, la
materialidad cambia, el presupuesto de comisiones se agota. Y el diseño central:

> **El presupuesto anual de avisos con orden ejecutable se DERIVA del presupuesto
> de comisiones. No se configura.** No puedes ser avisado de actuar más veces de
> las que puedes pagar por actuar.

Esto se auditó adversarialmente. Los números, antes y después de arreglar nueve
defectos que la auditoría encontró:

| Escenario adversarial (366 evaluaciones diarias) | Antes | Después |
|---|---:|---:|
| Avisos totales al año | 195 | **60** |
| Peor ventana de 30 días | 20 | **5** |
| Avisos que cargan una orden ejecutable | 23 | **1** |
| Caída de Banxico intermitente → avisos/año | 365 | **48** |
| Hurdle oscilando 60 pb y terminando donde empezó | 18 | **1** |
| Deriva de +2 pb/día durante un año (+730 pb) | **0** ⚠️ | **14** |

Esa última fila es la que más importa: el diseño original habría dejado pasar un
ciclo completo de alza de Banxico en silencio, porque comparaba contra ayer en
vez de contra la última vez que te avisó.

### Noticias: solo pueden reducir o bloquear

Invariante duro, con test de propiedad que lo martillea con >700 entradas
adversariales (NaN, infinitos, `10**400`, strings, objetos vacíos): el
combinador devuelve un multiplicador acotado a **[0.0, 1.0]**. Nada puede
aumentar el tamaño de la posición. Dos usos legítimos:

1. **Corroborar estrés** — Fear & Greed extremo, DVOL o VIX elevados, volumen
   de noticias anómalo → recortar tamaño. Nunca "el sentimiento mejoró, compra".
2. **Detectar ruptura estructural** — que la CNBV cambie el estatus de Binance,
   que el SAT publique criterio sobre activos virtuales, que la LIF cambie la
   retención, que se modifique el art. 93 o 134 de la LISR. Eso invalida **el
   modelo**, no el precio. Levanta un bloqueo que exige revisión humana.

La lista de palabras clave está sintonizada para **sobre-disparar** a propósito:
un falso positivo cuesta una revisión manual, un falso negativo cuesta la
validez de todo el modelo.

Y la regla que más gente se salta: **una fuente caída nunca se lee como calma.**
Se lee como ceguera, y dos fuentes ciegas recortan el tamaño a 0.60x.

### Eventos de calendario: el reemplazo honesto del "tiempo real"

No puedes predecir qué hará Banxico. Sabes exactamente **cuándo** lo hará. El
aviso correcto no es "compra ahora", es:

> *Banxico decide el 24 de septiembre. Si recorta 50 pb, tu hurdle baja de
> 10.84% a X% y el sleeve objetivo sube a Y MXN.*

`events.py` trae el calendario (Banxico 24-sep / 5-nov / 17-dic 2026, FOMC, CPI
de EE.UU., subastas de CETES los martes) y `escenarios_banxico()` precalcula el
hurdle y el sleeve resultante para −50 / −25 / sin cambio / +25 pb. Es escenario
declarado como tal, no pronóstico.

## 3. Los dos bloqueadores que descubrió la verificación

### ⛔ Binance no es alcanzable desde GitHub Actions — RESUELTO

`api.binance.com` devuelve **HTTP 451 desde IPs de Estados Unidos**, y los
runners de GitHub Actions son estadounidenses. La arquitectura del cron —el
corazón del proyecto— no habría corrido ni una vez.

`data-api.binance.vision` probablemente funciona, pero Binance no documenta
ninguna excepción geográfica y su propio personal dice en el foro de
desarrolladores que los servidores en EE.UU. no funcionan. Apostar la
arquitectura a un "probablemente" no documentado es justo lo que este repo
existe para no hacer.

**Resuelto**: `sources/market_data.py` con cascada **Kraken → Coinbase →
Binance**. Kraken primero porque devuelve ~720 velas diarias en una sola
petición (el motor necesita 210 mínimo, 500 ideal) — no paginar es no tener bugs
de paginación. Ambos verificados en vivo, sin llave. Binance queda al final,
útil sólo corriendo desde tu Mac.

Efecto colateral necesario: los activos ahora son **canónicos** (`BTC`, `ETH`),
no pares de un exchange. Antes el snapshot publicaba `BTCUSDT` aunque el precio
viniera de otro lado. Por eso el esquema subió a **3.0.0**.

### ⚠️ Los IDs de serie de Banxico siguen sin verificar — PENDIENTE, ES EL PROMPT 1

| Serie | Estado |
|---|---|
| `SF43718` FIX, `SP68257` UDIS, `SF61745` tasa objetivo | ✅ confirmados |
| `SF60633` CETES 28d | ⚠️ segunda mano, no contra el catálogo oficial |
| `SF60634/35/36` CETES 91/182/364d | ❌ **cero fuentes** |
| `SP74665` "INPC" | ❌ **casi seguro es inflación NO SUBYACENTE** |

Los rangos `SANITY` **no** te protegen de esto: una serie de CETES con el plazo
equivocado cae igual dentro de [0.5%, 30.0%], y la inflación no subyacente cae
dentro de [−5%, 40%]. Atrapan basura, no atrapan lo plausible-pero-equivocado.
Todo el hurdle descansa ahí.

Dato relevante: en SIE conviven al menos **tres familias de CETES**.
`SF282/SF3338/SF3270/SF3367` son promedio mensual; `SF43936` es la semanal del
cuadro CF107 (resultados de subasta a fecha de colocación = "mercado primario");
la familia `SF606xx` es otro set. Elige a propósito.

## 4. Registro de fuentes — verificado el 10-ago-2026

Cada una: endpoint exacto, si necesita llave, y la trampa.

### Sin llave, verificadas en vivo

| Fuente | Endpoint | Trampa |
|---|---|---|
| **Kraken OHLC** | `api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440` | La llave del resultado es el código interno (`XXBTZUSD`), **no** el `pair` que mandaste. Toma la primera llave distinta de `last`. Tope ~720 velas |
| **Coinbase Exchange** | `api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400` | El array es `[time, low, high, open, close, volume]` — **no** es orden OHLC. Cierre en índice 4. Tope ~300/petición, 10 req/s |
| **Fear & Greed** | `api.alternative.me/fng/?limit=N&format=json` | `timestamp` es Unix en **string**. Actualiza 1 vez al día ~00:00 UTC |
| **Deribit DVOL** | `deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&...&resolution=1D` | `result.data` son **arrays** `[ts_ms, o, h, l, c]`, no objetos. Sólo BTC y ETH |
| **GDELT DOC 2.0** | `api.gdeltproject.org/api/v2/doc/doc?query=...&mode=TimelineVol&format=json` | Rate-limita agresivo: **429 y luego 500 en pruebas en vivo hoy**. Exige User-Agent explícito y backoff |
| **BLS calendario** | `bls.gov/schedule/news_release/bls.ics` | Formato ICS real. Filtra por `SUMMARY` con "Consumer Price Index" |
| **Expansión RSS** | `expansion.mx/rss` | RSS 2.0 válido, es-mx |

### Con llave gratuita

| Fuente | Cómo | Límites |
|---|---|---|
| **Banxico SIE** | `banxico.org.mx/SieAPIRest/service/v1/token` | 20 series/petición, 80 req/min, 40,000/día |
| **FRED** | `fredaccount.stlouisfed.org` | Series confirmadas: `VIXCLS`, `DTWEXBGS` (**no existe el DXY de ICE en FRED**; DTWEXBGS arrastra ~2 días hábiles), `DGS10`, `DFEDTARU/L` |

### Problemáticas — el código ya degrada

| Fuente | Problema |
|---|---|
| **DOF vía SIDOF** | `sidof.segob.gob.mx/datos_abiertos/getJSON/65` existe, pero los query params están **sin documentar**. Hay que capturarlos del inspector de red. Mientras tanto es una fuente caída permanente |
| **CNBV** | **Cadena TLS incompleta** — `requests.get()` truena con `CERTIFICATE_VERIFY_FAILED` en un runner limpio. No hay RSS. Consigue la señal vía DOF |
| **El Economista** | HTTP 403 a todo cliente no-navegador. Excluido |
| **El Financiero / Bloomberg Línea** | Arc XP, requieren `?outputType=xml` y devuelven **gzip** |
| **Banxico calendario, SAT, convocatorias CETES** | Todo PDF-first o renderizado en JS. Las fechas están hardcodeadas en `events.py` con comentario |

## 5. La secuencia de prompts

Trabaja en el Mac, en el repo desempaquetado. `CLAUDE.md` en la raíz tiene las
diez reglas; Claude Code lo lee solo.

### Paso 0 — Preparar

```bash
cd ~/inversor-min
git init && git add -A && git commit -m "motor verificado, 174 tests"
gh repo create inversor-min --public --source=. --push

open https://www.banxico.org.mx/SieAPIRest/service/v1/token
gh secret set BANXICO_TOKEN
open https://fredaccount.stlouisfed.org/apikey        # opcional pero recomendado
gh secret set FRED_API_KEY
```

Repo **público** a propósito: el snapshot no lleva datos personales, así que
`raw.githubusercontent.com` sirve el JSON sin autenticación y la app no necesita
ningún secreto.

---

### Prompt 1 — Verificar las series (empieza aquí)

> Lee `CLAUDE.md` y `engine/src/inversor/sources/banxico.py`. Con `BANXICO_TOKEN` en el entorno, corre `python -m inversor verify-series` y enséñame el título oficial de cada serie.
>
> Los IDs de CETES 91d, 182d y 364d (`SF60634/35/36`) no tienen ni una fuente que los respalde, y `SP74665` casi seguro es inflación **no subyacente** en vez de INPC general. Si un título no corresponde, encuentra el correcto en el catálogo de Banxico y corrígelo en `SERIES`. Ten presente que en SIE conviven al menos tres familias de CETES —promedio mensual, la semanal del cuadro CF107, y la familia SF606xx— y que queremos la de subasta primaria.
>
> Después: los rangos `SANITY` sólo atrapan basura, no atrapan lo plausible-pero-equivocado. Agrega validación estructural que sí lo atrape — que la curva CETES sea monótona por plazo dentro de una tolerancia, y que el título de cada serie contenga el número de días que esperamos. Escribe el test.
>
> No cambies nada más. Al terminar, dime exactamente qué IDs corregiste y con qué fuente.

### Prompt 2 — Probar que la cascada de venues funciona desde CI

> Lee `engine/src/inversor/sources/market_data.py`. Verifica desde tu máquina que `kraken_daily("BTC")` y `coinbase_daily("BTC")` devuelven al menos 210 velas con fechas correctas y precios plausibles.
>
> Luego lo importante: **prueba la cascada desde un runner de GitHub Actions, no desde mi Mac.** Escribe un workflow de un solo paso (`workflow_dispatch`) que corra los tres venues y reporte cuál funcionó y cuál falló con qué código. La hipótesis a comprobar es que Binance devuelve 451 desde la IP estadounidense del runner y Kraken no. Si Kraken también falla desde CI, dímelo de inmediato: cambia la arquitectura.
>
> Escribe tests con respuestas grabadas (fixtures del JSON real que capturaste) que verifiquen el parseo de cada venue — en particular que Coinbase es `[time, low, high, open, close, volume]` y no OHLC, y que la llave del resultado de Kraken es el código interno y no el `pair`.

### Prompt 3 — Primera corrida real end-to-end

> Corre `python -m inversor run --capital 50000 --horizon 364 --dry-run` y enséñame la salida completa, incluido el bloque de notificaciones.
>
> Espero que la primera corrida NO emita ninguna notificación de acción: no hay snapshot previo con qué comparar, y el silencio es el comportamiento correcto. Si emite algo que parezca una orden, es un bug: repórtalo antes de seguir.
>
> Verifica que `data_freshness` traiga entradas `precio_BTC` y `precio_ETH` con el venue que las sirvió, y que `market.venues` esté poblado. Compara los números contra `docs/PRD-y-plan.md` §0 — el hurdle debería salir cerca de 10.8% anualizado si la inflación real sigue en 3.12%.

### Prompt 4 — Activar el cron y las notificaciones

> Revisa `.github/workflows/daily.yml`. Actualízalo para que también persista `notifications.json` y `notifications-latest.json`, y actívalo con `gh workflow run decision-diaria`.
>
> Detalle de calendario: la subasta de CETES es los **martes** con colocación el jueves, y el FIX se publica ~12:30 CDMX. Confirma que el cron a las 14:00 CDMX captura el dato del día.
>
> Añade la entrega de avisos por **ntfy.sh**: un paso que haga POST del contenido de `notifications-latest.json` a un topic con nombre largo y aleatorio, sólo cuando hay avisos. Sin cuenta, sin infra, sin FCM. Mapea la prioridad del aviso a la de ntfy. `notify_sinks.py` ya tiene el renderizador.
>
> **Crítico**: `notifications.json` es append-only. Es el log Y la memoria de cooldowns e histéresis entre corridas. Si el workflow lo sobrescribe en vez de anexar, el anti-spam pierde el estado y el sistema vuelve a avisar de todo. Escribe una verificación en el workflow que falle si el archivo se encoge.

### Prompt 5 — Conectar señales de estrés y noticias al motor

> `signals.py`, `events.py`, `sources/market_stress.py` y `sources/news.py` están construidos y testeados en aislamiento, pero **no están conectados a `decide.py`**. Conéctalos:
>
> El multiplicador de `SignalState` se compone con el multiplicador de régimen tomando el **mínimo**, no el producto — F&G, DVOL y VIX leen el mismo estado por tres ventanas distintas y multiplicarlos cuenta el estrés tres veces. Los blockers de ruptura estructural entran a `Decision.blockers`. Las razones entran a `Decision.reasons`. Las fuentes caídas van a `Decision.warnings` y, si son dos o más, recortan tamaño.
>
> Escribe el test que prueba, sobre `decide()` completo, que ninguna combinación de señales de noticias puede producir un peso cripto MAYOR que el que produce el motor sin ellas. Esa es la regla 8 y es la que hace que esta feature no sea una máquina de sobreoperar.
>
> Empieza con GDELT y DOF **desactivados por bandera** hasta el Prompt 6. Hoy los dos fallan y dos fuentes caídas recortan el tamaño a 0.60x permanentemente, lo cual sería correcto por diseño pero inútil en la práctica.

### Prompt 6 — Arreglar las dos fuentes rotas

> Dos fuentes están codificadas pero no funcionan. Arréglalas o quítalas — dejarlas caídas permanentemente hace que el recorte por ceguera sea el estado normal, y un recorte que siempre está activo no es información.
>
> **DOF/SIDOF**: `sidof.segob.gob.mx/datos_abiertos/getJSON/65` existe, pero sus query params están sin documentar. Abre el portal en el navegador, captura del inspector de red las peticiones reales que hace, y codifica los params correctos. Si no logras una consulta por fecha confiable en una sesión, quita DOF del set de fuentes y dilo — es mejor una fuente menos que una fuente permanentemente ciega.
>
> **GDELT**: rate-limita agresivamente (429 y luego 500 en pruebas). Ya tiene backoff exponencial con jitter. Mide cuántas peticiones al día tolera realmente y ajusta la frecuencia. Si sigue siendo inestable, quítalo: la respuesta correcta es sacarlo del set, no aflojar el umbral.

### Prompt 7 — Android

> Lee `android/README.md`. El esquema del snapshot subió a **3.0.0**: las llaves de `allocation_mxn` ahora son `BTC`/`ETH` en vez de `BTCUSDT`/`ETHUSDT`, y `market.venues` y las entradas `precio_*` de `data_freshness` son nuevas. Actualiza el DTO y los tests contra el `snapshots/latest.json` regenerado.
>
> Añade una cuarta pantalla, **Avisos**, que lea `snapshots/notifications-latest.json`: cada aviso con su razonamiento y su estrategia, y una marca visible en los que cargan una orden ejecutable. Muestra también los suprimidos, colapsados — que el usuario pueda ver qué NO se le avisó y por qué es parte de que confíe en el silencio.
>
> Genera el wrapper (`gradle wrapper --gradle-version 8.9`), pon tu OWNER/REPO en `app/build.gradle.kts`, corre `./gradlew test` y `./gradlew assembleDebug`, e instala con `adb install -r`. Los tres riesgos conocidos de primer compile están en `android/README.md`.
>
> **No publiques en Play Store.** Ver §7 de este documento.

### Prompt 8 — Al día 60, no antes

> Lee todos los archivos de `snapshots/` y `snapshots/notifications.json`. Construye un análisis walk-forward que conteste una sola pregunta: **¿la asignación recomendada le ganó a quedarse 100% en CETES, neta de comisiones e impuestos?**
>
> Usa precios reales para valuar cada decisión pasada. Reporta: rendimiento acumulado vs CETES puro, máxima caída, operaciones que el sistema autorizó, comisiones realmente gastadas, cuántos días la recomendación fue `STAY_IN_CETES`, y —clave para evaluar la capa de avisos— cuántas notificaciones se emitieron, cuántas cargaban una orden, y cuántas resultaron ser ruido en retrospectiva.
>
> **No optimices parámetros para mejorar el resultado.** El punto es medir, no ajustar. Si la estrategia perdió contra CETES, dilo sin suavizarlo.

---

## 6. Lo que NO debes pedirle a Claude Code

Ejecución automática de órdenes · guardar llaves de exchange en cualquier lado ·
apalancamiento, futuros o perpetuos · alts fuera de BTC/ETH · puntuar
sentimiento de noticias para cronometrar entradas · optimizar parámetros contra
el histórico · publicar en Play Store · aflojar el presupuesto de notificaciones
porque "avisa poco".

Ese último merece una nota: si el sistema te avisa poco, **está funcionando**.
La salida más frecuente y más valiosa de esta herramienta es el silencio.

## 7. Perímetro regulatorio

**Uso personal (lo que elegiste): limpio.** Sideload de APK, sin Play Store, sin
declaración financiera de Google, sin registro RAI ante CNBV — cripto no es
"valor" y no hay terceros.

**Si algún día lo distribuyes**, se activan tres cosas a la vez: la Financial
features declaration de Google para apps de inversión y cripto *incluida
asesoría personalizada*; el registro RAI si el alcance toca valores con
habitualidad y cobro; y —lo que más te expone— eres asesor registrado de la AEEJ
mientras PBD cobra due diligence a fondos y comisiones de proveedores. Una app
pública de recomendación te agrega una superficie de conflicto para la cual **no
tienes política de disclosure**. La línea a no cruzar sin decisión consciente es
el momento en que una segunda persona actúa sobre las señales.

## 8. Hechos que siguen sin verificar

Cada uno alimenta un cálculo de dinero.

| # | Elemento | Consecuencia si está mal |
|---|---|---|
| 1 | IDs de serie CETES 91/182/364d | El hurdle se calcula sobre el plazo equivocado. **Prompt 1** |
| 2 | `SP74665` probablemente es inflación no subyacente | Sesga el interés real y el ISR. **Prompt 1** |
| 3 | **La exención 3×UMA aplicada a cripto: el SAT no ha publicado nada** — ni criterio normativo (Anexo 7 RMF 2026), ni no vinculativo (Anexo 3), ni regla de RMF | El ISR efectivo pasa de 0% a marginal y el hurdle sube ~150 pb. **Esta es la pregunta para tu contador, no para Claude Code** |
| 4 | El texto de LISR 93-XIX-b dice "salario mínimo elevado al año", no UMA — la sustitución viene de la desindexación de 2016 | El monto exento podría no ser 128,383.92 MXN |
| 5 | Tu tasa marginal de ISR (0.30 es placeholder) | Mueve el hurdle ~100 pb |
| 6 | El plazo largo de la subasta del 4-ago: una fuente dice 350d, otra 364d | Afecta el calce de plazo |
| 7 | Fechas de Banxico 24-sep / 5-nov / 17-dic 2026: **derivadas**, no leídas de un campo limpio | `events.py` daría escenarios en fechas equivocadas |
| 8 | Los umbrales de `signals.py` (`MULT_FG_MIEDO_EXTREMO = 0.50` y hermanos) | Son juicios sin calibrar contra nada. Están nombrados y juntos a propósito |

## 9. Estado del código

```
174 tests pasando · cero dependencias de terceros en runtime · cero llaves de exchange

engine/tests/test_engine.py    33   motor, fiscal, riesgo, costos, frescura, venues
engine/tests/test_signals.py   66   invariante asimétrico, eventos, escenarios
engine/tests/test_notify.py    75   anti-spam adversarial, cooldowns, presupuesto
```

Lo que **no** está probado: nada en vivo. Este sandbox no alcanza Banxico,
Kraken, Coinbase, GDELT ni ninguna otra fuente. Todos los fetchers están
escritos contra endpoints verificados documentalmente y probados con fixtures,
pero **ninguno ha hecho una sola petición real**. Los Prompts 1–3 existen
precisamente para eso.
