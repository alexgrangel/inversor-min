package mx.inversor.min

/**
 * Configuración de la app. No hay llaves, no hay secretos, no hay backend:
 * lo único configurable es a qué repositorio público apuntar.
 *
 * El repo se define en `app/build.gradle.kts` (val snapshotRepo) y llega aquí
 * como BuildConfig.SNAPSHOT_REPO. Ese es el único punto de edición.
 */

/** Versión mayor de `schema_version` contra la que se construyó esta app. */
const val SUPPORTED_SCHEMA_MAJOR: Int = 1

/** Antigüedad máxima del snapshot antes de marcarlo rancio en la UI. */
const val MAX_SNAPSHOT_AGE_DAYS: Long = 3

const val SNAPSHOTS_DIR: String = "snapshots"
const val LATEST_FILE: String = "latest.json"

// Funciones puras (top-level, sin tocar BuildConfig) para que sean testeables
// desde JVM sin generar la clase BuildConfig.

fun rawContentUrl(repo: String, branch: String, path: String): String =
    "https://raw.githubusercontent.com/$repo/$branch/$path"

fun contentsApiUrl(repo: String, branch: String, dir: String): String =
    "https://api.github.com/repos/$repo/contents/$dir?ref=$branch"

object AppConfig {
    val repo: String get() = BuildConfig.SNAPSHOT_REPO
    val branch: String get() = BuildConfig.SNAPSHOT_BRANCH

    val latestUrl: String get() = rawContentUrl(repo, branch, "$SNAPSHOTS_DIR/$LATEST_FILE")
    val historyIndexUrl: String get() = contentsApiUrl(repo, branch, SNAPSHOTS_DIR)

    /** true cuando todavía no se editó el placeholder del build.gradle.kts. */
    val isPlaceholderRepo: Boolean get() = repo == "OWNER/REPO"
}
