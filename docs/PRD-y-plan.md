# inversor-min — PRD, plan técnico e instrucciones para Claude Code

Alex González Rangel · 10 de agosto de 2026
Parámetros fijados por el usuario: capital < 50,000 MXN · solo recomendar (read-only) · uso personal · Revolut cuenta México

---

## 0. Diagnóstico previo: por qué el objetivo original no se puede construir

El encargo fue "recomendar en qué invertir, con los mejores instrumentos, con el
menor dinero y el mayor rendimiento". Eso no es una función objetivo: es una
descripción de apalancamiento. Con capital chico, la selección de instrumento
—que es lo que una app "recomendadora" resuelve— explica una fracción menor del
resultado. Lo explican el drag de comisiones, la aritmética fiscal y el tipo de
cambio.

Los números, calculados con el motor de este repo sobre datos verificados de
agosto de 2026:

| | |
|---|---|
| CETES 364d nominal | **7.01%** |
| Inflación anual INPC (julio 2026) | **3.12%** |
| Base gravable, LISR art. 134 (resta, no Fisher) | 3.89% |
| ISR al 30% marginal | −1.17% |
| **CETES neto nominal** | **5.84%** |
| CETES neto real | 2.64% |
| Prima de riesgo exigida para tomar vol de ~50% + FX sin cobertura | +5.00% |
| **Hurdle que cripto debe superar, en pesos** | **10.84%** |

Y el presupuesto de comisiones: 0.50% del monto que rota, dividido entre 0.30%
por operación completa (0.10% comisión + 0.05% slippage, dos lados) = **1.7
operaciones al año**. Cualquier app que te sugiera operar más seguido que eso, a
este tamaño de cuenta, está transfiriendo tu capital al exchange.

Con esos insumos, el dimensionamiento por presupuesto de pérdida (8% de caída
tolerable del portafolio / 75% de caída supuesta del activo) da un sleeve cripto
de **1,440 MXN**. El veredicto del motor es **INMATERIAL**:

| Si cripto hace… | Impacto en tu portafolio | En pesos |
|---|---:|---:|
| −50% | −1.44% | −720 MXN |
| +50% | +1.44% | +720 MXN |
| **+100%** | **+2.88%** | **+1,440 MXN** |

Contra eso, CETES paga **2,545 MXN al año, neto, sin volatilidad**. Es decir:
BTC tiene que *duplicarse* para que la posición cripto iguale lo que CETES te
paga por no hacer nada. Y eso antes de tocar el tipo de cambio: con el peso en
17.14 y apreciándose (−1.69% en 30 días), si se aprecia otro 10% cripto necesita
**23.46% en dólares** sólo para empatar a CETES.

**Conclusión, sin diplomacia:** a 50,000 MXN no existe un problema de selección
de instrumentos que resolver. Existe un problema de no destruir el 5.84% que ya
tienes garantizado. La app correcta no es un recomendador de oportunidades: es
una **compuerta que dice que no** y muestra exactamente por qué.

Esa app sí vale la pena construirla, por tres razones que no son el rendimiento:
(a) te da el log walk-forward que en 12 meses te dirá si tu criterio sirve,
(b) el mismo motor escala sin cambios cuando el capital sea 10x, (c) es el
artefacto E1 de tu escalera de evidencia — lógica documentada y fechada, no
resultados prometidos.

### Corrección de un supuesto de tu stack

Tienes el MCP de Revolut X instalado en tu Mac, pero `check_auth_status` devuelve
**"Not configured"** y el tarifario oficial de Revolut X pertenece a **Revolut
Digital Assets Europe Ltd (RDAEL)**, entidad del EEE. Tu cuenta Revolut es de
México (banco autorizado por CNBV, beta desde nov-2025). No hay confirmación de
que Revolut X esté habilitado para residentes mexicanos. Sus herramientas
`grid_backtest` y `grid_optimize` no van a servirte hasta que eso cambie.

El venue del proyecto es **Binance** (opera en México bajo la Ley Fintech, sin
restricciones vigentes). Respaldo con licencia CNBV activa si Binance cambia de
estatus: **Bitso**.

---

## 1. Mini-PRD

### Objetivo

Una app Android personal que responde **una** pregunta cada día: dado el costo de
oportunidad libre de riesgo en México, el presupuesto de pérdida del usuario y el
costo de operar, ¿debe mover pesos fuera de CETES? Y si no, por qué no.

### No-objetivos (explícitos)

Pronosticar precios · ejecutar órdenes · apalancamiento, futuros o perpetuos ·
activos fuera de BTC/ETH · distribución en Play Store · optimización de
parámetros sobre backtests · cualquier forma de "señal predictiva".

### Requisitos funcionales

| # | Requisito |
|---|---|
| F1 | Calcular el hurdle: CETES del plazo que calza el horizonte, neto de ISR sobre interés real (LISR 134), más prima de riesgo explícita |
| F2 | Dimensionar el sleeve cripto como el mínimo de tres restricciones independientes: vol-target, presupuesto de caída, tope duro |
| F3 | Aplicar un multiplicador de régimen que **sólo reduce**, nunca amplifica |
| F4 | Imponer un presupuesto anual de comisiones y **bloquear** la operación cuando se agota |
| F5 | Publicar el rendimiento en pesos que el sleeve necesita para justificarse, y su sensibilidad al tipo de cambio |
| F6 | Emitir un veredicto de materialidad: si el sleeve no mueve la aguja, decirlo |
| F7 | Escribir cada decisión a un snapshot inmutable versionado en git |
| F8 | Cliente Android read-only que renderiza el snapshot, con historial navegable |

### Requisitos no funcionales

| # | Requisito |
|---|---|
| NF1 | **Cero llaves de API de exchange** en todo el sistema |
| NF2 | Cero servidores, cero costo recurrente (GitHub Actions + raw.githubusercontent) |
| NF3 | Engine sin dependencias en runtime (stdlib pura) |
| NF4 | Datos rancios **bloquean**, no degradan |
| NF5 | Ninguna tasa, comisión o umbral escrito a mano fuera de `config.py` |
| NF6 | El snapshot no contiene datos personales |
| NF7 | Tests sin red; todo bloqueo duro con test que demuestre que bloquea |

### Criterios de aceptación

1. `pytest` pasa sin red. ✅ **29/29**
2. `verify-series` confirma cada ID de serie de Banxico contra su título oficial. ⚠️ **pendiente: requiere tu token**
3. Con horizonte de 28 días, el hurdle del periodo es <2% y el anualizado ~10.8%. Nunca se confunden. ✅
4. `sum(allocation_mxn) == capital_total` en **todas** las ramas, incluida presupuesto agotado. ✅
5. Con datos rancios, el snapshot trae `blockers` y **nada** derivado: `hurdle`, `sizing`, `required_returns` vacíos. ✅
6. Un cambio de nombre de campo en el snapshot rompe un test de Android, no la app en producción. ✅
7. En una semana de corridas, el motor recomienda `STAY_IN_CETES` al menos una vez. ⚠️ **pendiente: requiere corridas reales**

### Edge cases cubiertos

| Caso | Comportamiento |
|---|---|
| Banxico o Binance caídos | `BLOCKED_STALE_DATA`, sin recomendación |
| ID de serie equivocado que devuelve un número absurdo | Excepción, no recomendación (rangos SANITY) |
| Sleeve por debajo del `MIN_NOTIONAL` de Binance en su **pata más chica** | `BLOCKED_BELOW_MIN_NOTIONAL` |
| Presupuesto de comisiones agotado | `BLOCKED_FEE_BUDGET`, mantener posición |
| Desviación menor que la banda de no-operación | `HOLD_NO_ACTION` (rebalancear cuesta más de lo que corrige) |
| Sleeve calculado = 0 | Sin división por cero fabricada; `max_round_trips = 0` |
| Interés real negativo | ISR = 0, no negativo |
| Exención 3×UMA consumida | ISR efectivo salta de 0% a marginal |
| Posición actual > capital invertible | Asignación se acota, sigue sumando el total |
| Serie de precios < 210 cierres | Excepción, no clasificación adivinada |
| Esquema del snapshot cambia | Android muestra "actualiza la app", no renderiza parcial |
| CETES 364d vs 350d según calendario de subasta | `pick_hurdle_tenor` elige por cercanía al horizonte |

### Casos NO cubiertos (deuda conocida)

- Frescura de la serie de Binance: `daily_closes` devuelve timestamps pero
  `__main__.py` los descarta. Una serie congelada es indistinguible de una fresca.
  **Es el primer arreglo pendiente.**
- `regime.py` corre sobre precios en USD; no hay clasificación de régimen del
  propio USD/MXN, que a este tamaño de cuenta pesa tanto como el activo.
- El horizonte es un solo número; no hay escalera de vencimientos de CETES.

---

## 2. Plan técnico

### Stack y por qué

| Capa | Elección | Razón |
|---|---|---|
| Cómputo | **GitHub Actions cron** | Gratis, secreto gestionado, y cada corrida queda committeada: el log walk-forward sale sin escribir código |
| Engine | **Python 3.11, stdlib pura** | Sin dependencias = sin actualizaciones que rompan un cron desatendido |
| Almacenamiento | **git** (`snapshots/*.json`) | Inmutable, versionado, auditable, cero costo |
| Transporte | **raw.githubusercontent.com** | Sin backend, sin auth, sin CDN que pagar |
| Cliente | **Kotlin + Jetpack Compose** | Nativo, sin runtime extra; app de 3 pantallas |
| Datos macro | **Banxico SIE API** | Fuente primaria: FIX, curva CETES, INPC, tasa objetivo |
| Datos cripto | **Binance público** | Sin autenticación ⇒ sin llaves que proteger |

La decisión de arquitectura que más importa: **el snapshot no lleva datos
personales**. Sólo tasas, pesos objetivo y razonamiento. Por eso el repo puede ser
público, la app no necesita autenticarse, y no hay ningún secreto en el APK.

### Fases

**Fase 0 — Motor headless (ya hecho, en este repo).** 29 tests, corrida
end-to-end verificada con datos reales de agosto 2026.

**Fase 1 — Conectar a datos en vivo (2–3 horas).** Token de Banxico,
`verify-series`, primera corrida real, activar el cron.

**Fase 2 — Paper, 60 días.** El cron corre solo. Tú no haces nada. Al final
tienes 40+ snapshots fechados y puedes contestar: ¿el motor le ganó a CETES?

**Fase 3 — Android (1 fin de semana).** El cliente ya está escrito en `android/`.
Compilar, sideload, usar.

**Fase 4 — Sólo si la Fase 2 lo justifica.** Subir capital, no agregar funciones.

Este orden no es negociable por una razón: el APK es andamio. El acto es el
motor corriendo con dinero real y el log acumulándose. Si construyes Android
primero, vas a tener una app bonita que renderiza una decisión sin historial.

### Modelo de seguridad

| Amenaza | Mitigación |
|---|---|
| APK descompilado | No hay nada dentro: sin llaves, sin tokens, sin credenciales |
| Repo público filtra info | El snapshot no lleva saldos, cuentas ni identificadores |
| Token de Banxico expuesto | Vive en GitHub Secrets; sólo lee datos públicos; revocable |
| Bot comprometido | El bot no puede operar: no existe API de trading en el sistema |
| MITM | HTTPS, `usesCleartextTraffic="false"` |
| Datos manipulados | Rangos SANITY + bloqueo por antigüedad |

Si algún día agregas ejecución: llaves **trade-only sin permiso de retiro**, con
IP whitelisted, en un secreto de servidor, **nunca** en el dispositivo. Y es otro
repo, con otro modelo de amenaza.

---

## 3. Hechos verificados y hechos por verificar

### Verificados contra fuente primaria o corroborados

| Dato | Valor | Estado |
|---|---|---|
| Tasa objetivo Banxico | 6.50% (6-ago-2026, segunda pausa consecutiva) | ✅ |
| Curva CETES, subasta 4-ago-2026 | 28d 6.17% · 91d 6.40% · 182d 6.75% · largo 7.01% | ✅ |
| USD/MXN FIX | 17.1387 (7-ago-2026), −1.69% en 30 días | ✅ |
| INPC general anual, julio 2026 | **3.12%** (subyacente 3.95%) | ✅ INEGI |
| UMA 2026 | $117.31 diaria → $42,794.64 anual → 3×UMA = **$128,383.92** | ✅ DOF 9-ene-2026 |
| Retención provisional sobre capital 2026 | **0.90%** — LIF 2026 **art. 24** (subió desde 0.50% en 2025) | ✅ |
| Subasta CETES | **martes**, colocación jueves (no al revés) | ✅ corregido |
| Revolut X | entidad RDAEL (EEE) | ✅ |
| Binance México | opera bajo Ley Fintech, sin restricciones vigentes | ✅ |
| Comisión Binance spot | 0.10% maker/taker, ~0.075% con BNB | ✅ |
| Google Play, apps financieras | exige Financial features declaration para gestión/inversión de dinero y cripto, incluida asesoría personalizada | ✅ |
| Banxico SIE | máx. 20 series/request, 80 req/min, 40,000/día | ✅ |

### ⚠️ NO verificados — cada uno alimenta un cálculo de dinero

| # | Elemento | Qué pasa si está mal |
|---|---|---|
| 1 | **IDs de serie CETES 91d/182d/364d** (`SF60634/35/36`). Cero fuentes. Sólo `SF60633` (28d) está corroborado, y de segunda mano | El hurdle se calcula sobre el plazo equivocado. Los rangos SANITY **no** lo atrapan: una serie de CETES con plazo incorrecto cae igual dentro de [0.5, 30.0] |
| 2 | **`SP74665` casi seguro NO es INPC general**: parece ser inflación *no subyacente* | Sesga el interés real y por tanto el ISR. Candidatos sin confirmar: `SP30578`, `SP74662` |
| 3 | **La exención 3×UMA aplicada a cripto.** El SAT **no ha publicado nada**: ni criterio normativo (Anexo 7 RMF 2026), ni no vinculativo (Anexo 3), ni regla de RMF | ISR efectivo pasa de 0% a marginal. Es **la** pregunta para tu contador |
| 4 | **El texto de LISR 93-XIX-b dice "salario mínimo elevado al año", no UMA.** La sustitución viene de la desindexación de 2016, no del texto | El monto exento podría no ser 128,383.92 |
| 5 | **Tu tasa marginal de ISR** (0.30 es placeholder) | Mueve el hurdle ~100 pb |
| 6 | El plazo largo de la subasta del 4-ago: una fuente dice **350d**, otra 364d | Afecta el calce de plazo |

Hay al menos **tres familias distintas de CETES** en SIE: `SF282/SF3338/SF3270/SF3367` son promedio mensual; `SF43936` es la semanal del cuadro CF107 (resultados de subasta a fecha de colocación = "mercado primario"); la familia `SF606xx` es otro set. Elige a propósito.

---

## 4. Instrucciones para Claude Code

Trabaja en el Mac, en el repo desempaquetado. `CLAUDE.md` en la raíz ya tiene las
reglas; Claude Code lo lee solo.

### Paso 0 — Preparar

```bash
cd ~/inversor-min
git init && git add -A && git commit -m "motor verificado, 29 tests"
gh repo create inversor-min --public --source=. --push
open https://www.banxico.org.mx/SieAPIRest/service/v1/token
gh secret set BANXICO_TOKEN
```

El repo **público** es deliberado: el snapshot no lleva datos personales y así
`raw.githubusercontent.com` sirve el JSON sin autenticación.

### Prompt 1 — Verificar las series (empieza aquí, es lo que más puede romper)

> Lee `CLAUDE.md` y `engine/src/inversor/sources/banxico.py`. Con `BANXICO_TOKEN` en el entorno, corre `python -m inversor verify-series` y enséñame el título oficial de cada serie.
>
> Los IDs de CETES 91d, 182d y 364d (`SF60634/35/36`) no están verificados contra ninguna fuente, y `SP74665` probablemente es inflación NO SUBYACENTE en vez de INPC general. Si un título no corresponde, encuentra el ID correcto consultando el catálogo de Banxico y corrígelo en `SERIES`.
>
> Además: los rangos `SANITY` sólo atrapan basura, no atrapan lo plausible-pero-equivocado. Agrega una validación estructural que sí lo atrape — por ejemplo, verificar que la curva CETES sea monótona por plazo dentro de una tolerancia, y que el título de cada serie contenga el número de días esperado. Escribe un test para esa validación.
>
> No cambies nada más. Cuando termines, dime exactamente qué IDs corregiste y con qué fuente.

### Prompt 2 — Primera corrida real y el arreglo pendiente

> Corre `python -m inversor run --capital 50000 --horizon 364 --dry-run` y enséñame la salida completa.
>
> Luego arregla el defecto documentado en `docs/PRD-y-plan.md` §1 "Casos NO cubiertos": la frescura de la serie de Binance nunca se revisa. `daily_closes` devuelve `(datetime, close)` pero `__main__.py` descarta los timestamps con `[c for _, c in ...]`. Una serie congelada o cacheada es indistinguible de una fresca, lo cual viola la regla 4 de `CLAUDE.md`.
>
> Cambia `decide()` para recibir `dict[str, list[tuple[datetime, float]]]` y bloquear con `BLOCKED_STALE_DATA` si el último cierre tiene más días que `policy.max_staleness_days`. Reporta la frescura de cada símbolo en `data_freshness` junto a las series de Banxico. Escribe el test que lo demuestre. Sube `SCHEMA_VERSION` si cambia el snapshot.

### Prompt 3 — Activar el cron

> Revisa `.github/workflows/daily.yml`. Corrígelo si hace falta y actívalo con `gh workflow run decision-diaria`. Verifica que el snapshot se commitea y que el resumen aparece en el step summary.
>
> Un detalle: la subasta de CETES es los **martes** con colocación el jueves. El cron corre 14:00 CDMX de lunes a viernes, después del FIX (~12:30). Confirma que ese horario captura el dato del día y ajústalo si no.
>
> Configura también las repository variables: `CAPITAL_MXN`, `RESERVE_MXN`, `HORIZON_DAYS`, `ISR_MARGINAL`, `HELD_MXN`, `FEES_YTD_MXN`.

### Prompt 4 — Android

> Lee `android/README.md`. Genera el gradle wrapper (`gradle wrapper --gradle-version 8.9`), pon tu OWNER/REPO en `app/build.gradle.kts`, corre `./gradlew test` y luego `./gradlew assembleDebug`.
>
> Los tres riesgos conocidos de primer compile están en `android/README.md`; atácalos si aparecen. Cuando compile, `adb install -r app/build/outputs/apk/debug/app-debug.apk`.
>
> **No** publiques en Play Store. Si la app llegara a distribuirse, activa la Financial features declaration de Google y el análisis de conflicto de interés que está en §5 de este documento.

### Prompt 5 — Al día 60, no antes

> Lee todos los archivos en `snapshots/`. Construye un análisis walk-forward que conteste una sola pregunta: **¿la asignación recomendada le ganó a quedarse 100% en CETES, neta de comisiones e impuestos?**
>
> Usa precios reales de Binance para valuar cada decisión pasada. Reporta: rendimiento acumulado de la estrategia vs CETES puro, máxima caída, número de operaciones que el sistema autorizó, comisiones realmente gastadas, y cuántos días la recomendación fue `STAY_IN_CETES`.
>
> No optimices parámetros para mejorar el resultado. El punto del ejercicio es medir, no ajustar. Si la estrategia perdió contra CETES, dilo sin suavizarlo.

### Lo que NO debes pedirle a Claude Code

Ejecución automática de órdenes · guardar llaves de exchange en cualquier lado ·
apalancamiento, futuros o perpetuos · alts fuera de BTC/ETH · optimizar
parámetros contra el histórico · publicar en Play Store. Cada una está prohibida
en `CLAUDE.md` con su razón.

---

## 5. Riesgo regulatorio y conflicto de interés

**Uso personal (lo que elegiste): perímetro limpio.** Sideload de APK, sin Play
Store, sin declaración financiera de Google. Recomendaciones habituales y
profesionales sobre **valores** activarían registro RAI ante CNBV, pero (a)
cripto no es "valor" y (b) no hay terceros. *(La fuente primaria de CNBV no fue
verificable: robots.txt bloquea el sitio. Trátalo como inferencia razonada.)*

**Si algún día lo distribuyes**, tres cosas se activan a la vez:

1. Google Play exige la Financial features declaration para apps de gestión o
   inversión de dinero y criptomonedas, **incluida asesoría personalizada**.
2. Si el alcance toca valores (ETFs, acciones, deuda corporativa) y hay
   habitualidad y cobro, entra el registro RAI.
3. **El punto que más te expone:** eres asesor registrado de la AEEJ y PBD cobra
   due diligence a fondos y comisiones de proveedores (8–15%). Una app pública de
   recomendación de inversión te agrega una superficie de conflicto para la cual
   **no tienes política de disclosure**. Esa política no existe hoy; distribuir la
   app antes de tenerla es amplificar exposición sin escalar el control.

Mientras sea de uso personal, nada de esto aplica. La línea que no debes cruzar
sin una decisión consciente es el momento en que una segunda persona actúa sobre
las señales.
