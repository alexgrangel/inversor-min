# android/ — cliente read-only

App de cuatro pantallas que lee `snapshots/latest.json` y
`snapshots/notifications-latest.json` de un repo público de GitHub y los
renderiza. **No opera, no guarda llaves, no tiene backend, no tiene login, no
manda telemetría.** Un solo permiso: `INTERNET`.

> **Esta app NO se publica en Play Store.** Es de uso personal, se instala por
> sideload en tu propio dispositivo. Distribuirla cambiaría el perímetro
> regulatorio (recomendaciones de inversión a terceros) y el modelo de riesgo.
> Ver `CLAUDE.md` en la raíz del repo.

---

## 1. Apuntar la app a tu repo

Una sola línea. En `app/build.gradle.kts`:

```kotlin
val snapshotRepo = "OWNER/REPO"   // <- pon aquí "tu-usuario/tu-repo"
```

Escríbelo como `usuario/repositorio`: sin `https://`, sin `.git`, sin espacios,
sin barra final. De ahí salen las dos URLs que consume la app:

- `https://raw.githubusercontent.com/<repo>/main/snapshots/latest.json`
- `https://api.github.com/repos/<repo>/contents/snapshots?ref=main`

Llega al código como `BuildConfig.SNAPSHOT_REPO` y se lee sólo en
`AppConfig.kt`. Si usas una rama distinta de `main`, cambia también
`SNAPSHOT_BRANCH` en el mismo bloque.

El repo tiene que ser **público**: la app no manda credenciales. Eso es a
propósito — el JSON no contiene datos personales.

---

## 2. Requisitos

| Herramienta | Versión |
|---|---|
| JDK | 17 |
| Gradle | 8.9 |
| Android Gradle Plugin | 8.7.3 |
| Kotlin | 2.0.21 |
| compileSdk / targetSdk | 35 |
| minSdk | 26 (Android 8.0) |

El repositorio no incluye el binario `gradle/wrapper/gradle-wrapper.jar`
(no se versionan binarios aquí). Genera el wrapper una vez, con un Gradle 8.9
ya instalado:

```bash
cd android
gradle wrapper --gradle-version 8.9
```

O simplemente abre la carpeta `android/` en Android Studio (Ladybug o posterior)
y deja que sincronice: crea el wrapper y descarga el SDK solo.

### Los tres riesgos conocidos de primer compile

Verificados en un primer build real (11-ago-2026, Mac limpio sin Android
Studio):

1. **No hay Java en el PATH.** `gradle` y el wrapper truenan con "Unable to
   locate a Java Runtime" antes de decir nada útil. Instala JDK 17 y exporta
   `JAVA_HOME` (Homebrew: `brew install openjdk@17`,
   `export JAVA_HOME=/opt/homebrew/opt/openjdk@17`).
2. **No hay `sdk.dir`.** Sin Android Studio, AGP no encuentra el SDK. Crea
   `android/local.properties` con `sdk.dir=<ruta del SDK>` (con
   `brew install android-commandlinetools`: la ruta es
   `/opt/homebrew/share/android-commandlinetools`) e instala los paquetes:
   `sdkmanager --licenses`, luego
   `sdkmanager "platform-tools" "platforms;android-35" "build-tools;35.0.0"`.
   `local.properties` está gitignoreado; no lo commitees.
3. **La primera descarga es grande y lenta.** El wrapper baja Gradle 8.9, AGP
   8.7.3 y todo Compose (~1-2 GB con el SDK). Si el build "se cuelga", está
   descargando; los siguientes builds son incrementales y rápidos.

---

## 3. Compilar

```bash
cd android

# Tests JVM primero. Si el engine cambió el esquema, esto truena aquí y no en
# el celular con un número equivocado en pantalla.
./gradlew test

# APK de depuración, firmado con la llave debug de tu máquina.
./gradlew assembleDebug
```

El APK queda en:

```
android/app/build/outputs/apk/debug/app-debug.apk
```

---

## 4. Instalar en tu dispositivo

1. En el teléfono: **Ajustes → Acerca del teléfono → toca 7 veces "Número de
   compilación"** para activar Opciones de desarrollador.
2. **Ajustes → Sistema → Opciones de desarrollador → Depuración por USB: ON**.
3. Conecta el cable y acepta el diálogo de autorización de la computadora.

```bash
adb devices              # debe listar tu dispositivo como "device", no "unauthorized"
adb install -r android/app/build/outputs/apk/debug/app-debug.apk
```

`-r` reinstala encima conservando los datos (incluida la caché del último
snapshot). Si cambiaste la firma o el `applicationId`, desinstala primero:

```bash
adb uninstall mx.inversor.min
```

Sin cable, también sirve copiar el APK al teléfono y abrirlo desde el
explorador de archivos, autorizando "instalar apps desconocidas" para esa app.

---

## 5. Qué muestra

**Hoy** — el chip de acción con código de color
(`STAY_IN_CETES` azul, `ALLOCATE_TO_CRYPTO` verde, `REDUCE_CRYPTO` ámbar,
`HOLD_NO_ACTION` gris, cualquier `BLOCKED_*` rojo), el `headline`, la asignación
objetivo, "¿Mueve la aguja?", el hurdle y el presupuesto de comisiones.

Dos cosas de esta pantalla no son decoración:

- **Las dos tasas del hurdle van en un bloque aparte y etiquetado.**
  `hurdle_total_anualizado` es una tasa por año; `hurdle_total_periodo` es lo
  que hay que ganar en `hurdle.horizon_days` días. Presentar la primera como si
  fuera la segunda infla el hurdle por el factor 365/horizonte (a 28 días, 13x).
  Los días salen del JSON, nunca están escritos en el código. En la misma tabla,
  `base_gravable_lisr134` (una resta, art. 134) va etiquetada distinto de
  `cetes_real_pretax` (la relación de Fisher) porque se parecen y no son lo mismo.
- **Cuando `sizing.materiality.veredicto` es `INMATERIAL`**, la pantalla lo dice
  arriba de todo, en ámbar, con `cetes_anual_mxn` como el número más grande de
  la app. Que el sleeve no mueva la aguja no es una nota al pie: es la respuesta.

**Por qué** — `reasons`, `warnings` y `blockers` completos, más la tabla de
sensibilidad al tipo de cambio. Los escenarios adversos (peso que se aprecia)
salen del cálculo multiplicativo del engine y son grandes: se muestran con los
mismos dos decimales que el resto, resaltados, sin `maxLines` y con la prosa del
engine debajo. Nada se recorta ni se abrevia.

**Historial** — el log walk-forward. Lista los `snapshots/AAAA-MM-DD.json` del
repo vía la contents API de GitHub; al tocar un día se descarga ese JSON y se
muestra su acción, su headline y sus números clave.

**Avisos** — `snapshots/notifications-latest.json`: los avisos de la última
corrida con su razonamiento y su estrategia completos. Dos cosas de esta
pantalla no son decoración:

- **Un aviso con `es_orden_ejecutable` lleva una marca imposible de no ver**
  (banda roja). Es la salida más cara del sistema: cuenta contra el presupuesto
  anual de avisos operables, que se DERIVA del presupuesto de comisiones
  (regla 9 del repo).
- **Los suprimidos se muestran, colapsados.** Ver qué NO se te avisó y por qué
  (cooldown, histéresis, presupuesto) es parte de poder confiar en el
  silencio. Y el silencio mismo se dice con todas sus letras: "sin cambios de
  estado" es la salida esperada, no una lista vacía.

---

## 6. Frescura del dato: cómo se comporta

Regla 4 del repo (`datos rancios bloquean, no degradan`), traducida a UI:

- Al abrir, la app pinta **de inmediato** el último snapshot guardado en
  almacenamiento interno, con un banner **"Datos guardados del &lt;fecha&gt;"**,
  y refresca en segundo plano.
- Si alguna entrada de `data_freshness` trae `stale: true`, **o** si
  `generated_at` tiene más de 3 días, aparece un **banner rojo permanente**
  arriba de las tres pantallas. No es un toast y no se puede descartar.
- Si `generated_at` no se puede leer, también cuenta como rancio.
- Si falla la descarga, se sigue viendo la caché, pero el banner dice que no se
  pudo actualizar. Nunca se muestran números viejos como si fueran de hoy.
- Si el **mayor** de `schema_version` no es el que esta app entiende
  (`SUPPORTED_SCHEMA_MAJOR` en `AppConfig.kt`), la app muestra una pantalla de
  "actualiza la app" y **no renderiza nada del snapshot**. Media pantalla
  correcta y media vacía es peor que ninguna.

---

## 7. Estructura

```
android/
  settings.gradle.kts
  build.gradle.kts
  gradle.properties
  gradle/libs.versions.toml            versiones pinneadas
  gradle/wrapper/gradle-wrapper.properties
  app/
    build.gradle.kts                   <- aquí se edita OWNER/REPO
    proguard-rules.pro
    src/main/AndroidManifest.xml       INTERNET, usesCleartextTraffic=false
    src/main/res/values/strings.xml    todos los textos en español
    src/main/java/mx/inversor/min/
      MainActivity.kt                  Activity única + Scaffold + banners
      MainViewModel.kt                 estado, caché primero y refresco
      AppConfig.kt                     URLs y constantes del contrato
      data/SnapshotDto.kt              espejo exacto de latest.json
      data/SnapshotRepository.kt       OkHttp, tres GET públicos
      data/LocalCache.kt               caché del último JSON bueno
      util/Format.kt                   formato es-MX (funciones puras)
      util/Freshness.kt                staleness y versión de esquema
      ui/theme/                        Material 3, claro y oscuro
      ui/components/                   chip de acción, tablas, banners
      ui/screens/                      TodayScreen, WhyScreen, HistoryScreen,
                                       AvisosScreen
      data/NotificationsDto.kt         espejo de notifications-latest.json
    src/test/                          tests JVM (sin emulador, sin red)
    src/test/resources/latest.json     copia literal del snapshot real
```

---

## 8. Cuando el engine cambie de esquema

1. Copia el `snapshots/latest.json` nuevo sobre
   `app/src/test/resources/latest.json`.
2. Corre `./gradlew test`. Si algún campo se renombró o desapareció, los tests
   truenan con `MissingFieldException`: eso es lo que tienen que hacer.
3. Ajusta `data/SnapshotDto.kt`.
4. Si el engine subió el **mayor** de `SCHEMA_VERSION`, sube también
   `SUPPORTED_SCHEMA_MAJOR` en `AppConfig.kt` y vuelve a instalar el APK.

Campos **nuevos** no requieren nada: `ignoreUnknownKeys = true`.

Si el engine renombra un campo **sin** subir el mayor de `SCHEMA_VERSION`, un
APK viejo no puede mostrar la pantalla de "actualiza la app" (no tiene forma de
saberlo). Lo que hace en ese caso es fallar el parseo y quedarse con la caché,
con el banner de "no se pudo actualizar" y el mensaje de formato incompatible.
Es la degradación correcta, pero es peor que subir el mayor: si vas a renombrar,
súbelo.

---

## 9. Lo que esta app no hace y no va a hacer

Órdenes, llaves de exchange, login, backend, analytics, notificaciones push,
SDKs de terceros, y publicación en Play Store. Si algo de eso hace falta, es
otro repo con otro modelo de amenaza.

**Uso personal. No es asesoría en inversiones.**
