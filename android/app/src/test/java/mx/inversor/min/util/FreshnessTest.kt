package mx.inversor.min.util

import mx.inversor.min.data.SnapshotDto
import mx.inversor.min.data.SnapshotParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

/**
 * Regla 4 del repo: datos rancios bloquean, no degradan. Aquí se prueba que la
 * app sabe reconocerlos; el banner rojo depende de esto.
 */
class FreshnessTest {

    private fun rawJson(): String =
        checkNotNull(javaClass.getResourceAsStream("/latest.json")) {
            "Falta app/src/test/resources/latest.json"
        }.bufferedReader(Charsets.UTF_8).use { it.readText() }

    private fun snapshot(raw: String = rawJson()): SnapshotDto = SnapshotParser.parse(raw)

    /** generated_at del snapshot de prueba (copia real del 11-ago-2026). */
    private val generatedAt: Instant = Instant.parse("2026-08-11T02:43:04.378265Z")

    @Test
    fun `snapshot reciente y sin series rancias no dispara el banner`() {
        val s = evaluateStaleness(snapshot(), generatedAt.plusSeconds(3600))
        assertFalse(s.isStale)
        assertFalse(s.tooOld)
        assertFalse(s.ageUnknown)
        assertEquals(0L, s.ageDays)
        assertTrue(s.staleSeries.isEmpty())
    }

    @Test
    fun `exactamente tres dias todavia no es rancio`() {
        val s = evaluateStaleness(snapshot(), generatedAt.plusSeconds(3 * 86_400))
        assertEquals(3L, s.ageDays)
        assertFalse(s.tooOld)
        assertFalse(s.isStale)
    }

    @Test
    fun `mas de tres dias es rancio`() {
        val s = evaluateStaleness(snapshot(), generatedAt.plusSeconds(4 * 86_400))
        assertEquals(4L, s.ageDays)
        assertTrue(s.tooOld)
        assertTrue(s.isStale)
    }

    @Test
    fun `una sola serie marcada stale basta para el banner`() {
        // El engine marca stale=true por serie; la primera del archivo es fix_usdmxn.
        val raw = rawJson().replaceFirst("\"stale\": false", "\"stale\": true")
        val s = evaluateStaleness(snapshot(raw), generatedAt.plusSeconds(60))
        assertTrue(s.isStale)
        assertFalse(s.tooOld)
        assertEquals(listOf("fix_usdmxn"), s.staleSeries)
    }

    @Test
    fun `varias series rancias se listan ordenadas`() {
        val raw = rawJson().replace("\"stale\": false", "\"stale\": true")
        val s = evaluateStaleness(snapshot(raw), generatedAt.plusSeconds(60))
        assertTrue(s.isStale)
        // 3.0.0: data_freshness también trae los precios cripto con su venue.
        assertEquals(
            listOf(
                "cetes_182", "cetes_28", "cetes_364", "cetes_91",
                "fix_usdmxn", "inpc_anual", "precio_BTC", "precio_ETH",
                "tasa_objetivo",
            ),
            s.staleSeries,
        )
    }

    @Test
    fun `generated_at ilegible se trata como rancio`() {
        val raw = rawJson().replace(
            "\"generated_at\": \"2026-08-11T02:43:04.378265+00:00\"",
            "\"generated_at\": \"anoche\"",
        )
        val s = evaluateStaleness(snapshot(raw), generatedAt)
        assertTrue(s.ageUnknown)
        assertTrue(s.isStale)
        assertNull(s.ageDays)
    }

    @Test
    fun `el limite de antiguedad es configurable`() {
        val s = evaluateStaleness(snapshot(), generatedAt.plusSeconds(2 * 86_400), maxAgeDays = 1)
        assertTrue(s.tooOld)
        assertTrue(s.isStale)
    }

    // ── Versión de esquema ────────────────────────────────────────────────

    @Test
    fun `mayor de esquema`() {
        assertEquals(1, schemaMajor("1.0.0"))
        assertEquals(1, schemaMajor("1"))
        assertEquals(2, schemaMajor("2.1.3"))
        assertEquals(10, schemaMajor("10.0.0"))
        assertNull(schemaMajor("v1.0.0"))
        assertNull(schemaMajor(""))
        assertNull(schemaMajor("no-soy-version"))
    }

    @Test
    fun `solo el mayor tres es compatible con esta app`() {
        assertTrue(isSchemaSupported("3.0.0"))
        assertTrue(isSchemaSupported("3.1.0"))
        assertTrue(isSchemaSupported("3.4.12"))
        assertFalse(isSchemaSupported("1.0.0"))
        assertFalse(isSchemaSupported("2.0.0"))
        assertFalse(isSchemaSupported("4.0.0"))
        assertFalse(isSchemaSupported("basura"))
    }

    @Test
    fun `el snapshot real es compatible`() {
        assertTrue(isSchemaSupported(snapshot().schemaVersion))
    }
}
