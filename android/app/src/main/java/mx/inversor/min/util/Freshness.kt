package mx.inversor.min.util

import mx.inversor.min.MAX_SNAPSHOT_AGE_DAYS
import mx.inversor.min.SUPPORTED_SCHEMA_MAJOR
import mx.inversor.min.data.SnapshotDto
import java.time.Instant

/**
 * Frescura del dato. Regla 4 del repo: datos rancios bloquean, no degradan.
 * En la app eso se traduce en un banner rojo permanente, nunca en un toast.
 *
 * Funciones puras para poder probarlas sin emulador.
 */
data class Staleness(
    val isStale: Boolean,
    /** Series de data_freshness marcadas stale=true por el engine. */
    val staleSeries: List<String>,
    /** Días de antigüedad de generated_at. Null si la fecha no se pudo leer. */
    val ageDays: Long?,
    val ageUnknown: Boolean,
    val tooOld: Boolean,
)

fun staleSeriesOf(snapshot: SnapshotDto): List<String> =
    snapshot.dataFreshness.filterValues { it.stale }.keys.sorted()

fun evaluateStaleness(
    snapshot: SnapshotDto,
    now: Instant,
    maxAgeDays: Long = MAX_SNAPSHOT_AGE_DAYS,
): Staleness {
    val series = staleSeriesOf(snapshot)
    val age = ageInDays(snapshot.generatedAt, now)
    val ageUnknown = age == null
    // Una fecha ilegible se trata como rancia: no se muestran números viejos
    // como si fueran de hoy sólo porque no supimos calcular la antigüedad.
    val tooOld = age != null && age > maxAgeDays
    return Staleness(
        isStale = series.isNotEmpty() || tooOld || ageUnknown,
        staleSeries = series,
        ageDays = age,
        ageUnknown = ageUnknown,
        tooOld = tooOld,
    )
}

// ── Versión de esquema ────────────────────────────────────────────────────

/** "1.0.0" -> 1. Null si la cadena no empieza con un entero. */
fun schemaMajor(version: String): Int? = version.trim().substringBefore('.').toIntOrNull()

/**
 * Un mayor distinto (o ilegible) significa que el contrato cambió: la app
 * muestra "actualiza la app" en vez de renderizar una vista parcial.
 */
fun isSchemaSupported(version: String, supportedMajor: Int = SUPPORTED_SCHEMA_MAJOR): Boolean =
    schemaMajor(version) == supportedMajor
