package mx.inversor.min.util

import java.math.RoundingMode
import java.text.DecimalFormat
import java.text.DecimalFormatSymbols
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.util.Locale

/**
 * Formateo para es-MX. Funciones puras, sin Context, sin Compose: se prueban
 * en JVM sin emulador.
 *
 * Los símbolos se fijan explícitamente (coma para miles, punto para decimales)
 * en vez de heredarlos del CLDR de la plataforma. Razón: el CLDR cambia entre
 * versiones de Android y de JDK, y un separador distinto rompería tanto los
 * tests como la lectura de números que el usuario compara a diario.
 */

// Locale("es","MX") en vez de Locale.of(): este último no existe en el
// android.jar de compileSdk 35.
@Suppress("DEPRECATION")
val LOCALE_MX: Locale = Locale("es", "MX")

/** Marcador para valores no representables (NaN, infinito, fecha ilegible). */
const val NO_VALUE: String = "—"

const val CURRENCY_SUFFIX: String = "MXN"

private fun mxSymbols(): DecimalFormatSymbols = DecimalFormatSymbols(LOCALE_MX).apply {
    groupingSeparator = ','
    decimalSeparator = '.'
    minusSign = '-'
}

private fun formatterFor(decimals: Int, forceSign: Boolean): DecimalFormat {
    val base = if (decimals <= 0) "#,##0" else "#,##0." + "0".repeat(decimals)
    // Subpatrón negativo explícito: DecimalFormat sustituye '-' por el símbolo
    // de menos y trata '+' como literal.
    val pattern = if (forceSign) "+$base;-$base" else base
    return DecimalFormat(pattern, mxSymbols()).apply { roundingMode = RoundingMode.HALF_UP }
}

/** 0.0701 -> "7.01%" */
fun formatPercent(value: Double, decimals: Int = 2): String =
    if (!value.isFinite()) NO_VALUE else formatterFor(decimals, false).format(value * 100.0) + "%"

/** -0.0216 -> "-2.16%" · 0.0432 -> "+4.32%" */
fun formatSignedPercent(value: Double, decimals: Int = 2): String =
    if (!value.isFinite()) NO_VALUE else formatterFor(decimals, true).format(value * 100.0) + "%"

/** 42840.0 -> "42,840 MXN" */
fun formatMxn(value: Double, decimals: Int = 0): String =
    if (!value.isFinite()) NO_VALUE
    else formatterFor(decimals, false).format(value) + " " + CURRENCY_SUFFIX

/** -1080.0 -> "-1,080 MXN" */
fun formatSignedMxn(value: Double, decimals: Int = 0): String =
    if (!value.isFinite()) NO_VALUE
    else formatterFor(decimals, true).format(value) + " " + CURRENCY_SUFFIX

/** 38.58024 -> "38.6" (sin sufijo) */
fun formatDecimal(value: Double, decimals: Int = 1): String =
    if (!value.isFinite()) NO_VALUE else formatterFor(decimals, false).format(value)

/** 0.45 -> "x0.45" */
fun formatMultiplier(value: Double): String =
    if (!value.isFinite()) NO_VALUE else "x" + formatterFor(2, false).format(value)

// ── Fechas ────────────────────────────────────────────────────────────────
// Formato numérico dd/MM/aaaa a propósito: no depende de nombres de mes del
// CLDR, así que es estable entre versiones de Android y determinista en tests.

private val OUT_DATE: DateTimeFormatter =
    DateTimeFormatter.ofPattern("dd/MM/yyyy").withLocale(LOCALE_MX)

private val OUT_DATE_TIME: DateTimeFormatter =
    DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm").withLocale(LOCALE_MX)

/** "2026-08-07" -> "07/08/2026". Devuelve la entrada si no es una fecha ISO. */
fun formatIsoDate(iso: String): String = parseIsoDateOrNull(iso)?.format(OUT_DATE) ?: iso

fun parseIsoDateOrNull(iso: String): LocalDate? = try {
    LocalDate.parse(iso, DateTimeFormatter.ISO_LOCAL_DATE)
} catch (e: DateTimeParseException) {
    null
}

/** "2026-08-10T02:51:56.993514+00:00" -> instante, o null si no parsea. */
fun parseIsoInstantOrNull(iso: String): Instant? = try {
    OffsetDateTime.parse(iso).toInstant()
} catch (e: DateTimeParseException) {
    null
}

/** generated_at ISO -> "09/08/2026 20:51" en la zona indicada. */
fun formatIsoDateTime(iso: String, zone: ZoneId): String =
    parseIsoInstantOrNull(iso)?.atZone(zone)?.format(OUT_DATE_TIME) ?: iso

/** generated_at ISO -> "09/08/2026" en la zona indicada. */
fun formatIsoInstantAsDate(iso: String, zone: ZoneId): String =
    parseIsoInstantOrNull(iso)?.atZone(zone)?.format(OUT_DATE) ?: iso

/** Días completos transcurridos entre generated_at y ahora. Null si no parsea. */
fun ageInDays(generatedAtIso: String, now: Instant): Long? =
    parseIsoInstantOrNull(generatedAtIso)?.let { Duration.between(it, now).toDays() }

/** "2026-08-10.json" -> "10/08/2026". Devuelve el nombre si no es fecha. */
fun formatSnapshotFileName(fileName: String): String =
    formatIsoDate(fileName.removeSuffix(".json"))
