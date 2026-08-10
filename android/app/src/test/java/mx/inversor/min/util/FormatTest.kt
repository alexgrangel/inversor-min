package mx.inversor.min.util

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.Instant
import java.time.ZoneId
import java.time.ZoneOffset

/**
 * Los números que aparecen aquí salen de snapshots/latest.json. Si el formato
 * cambia, alguien tiene que decidirlo a propósito, no descubrirlo en el celular.
 */
class FormatTest {

    // ── Porcentajes ───────────────────────────────────────────────────────

    @Test
    fun `porcentaje con dos decimales`() {
        assertEquals("7.01%", formatPercent(0.0701))
        assertEquals("3.12%", formatPercent(0.031200000000000002))
        assertEquals("5.84%", formatPercent(0.058429999999999996))
        assertEquals("3.89%", formatPercent(0.03889999999999999))
        assertEquals("3.77%", formatPercent(0.037723041117145195))
        assertEquals("0.30%", formatPercent(0.003))
        assertEquals("51.47%", formatPercent(0.5147316889043781))
    }

    /**
     * Las dos tasas del hurdle y los dos requeridos. Se formatean igual, así
     * que lo único que las distingue en pantalla es la etiqueta: por eso viven
     * en filas separadas y etiquetadas en TodayScreen.
     */
    @Test
    fun `las dos tasas del hurdle se formatean sin colapsar`() {
        assertEquals("10.84%", formatPercent(0.10843))               // anualizado
        assertEquals("10.81%", formatPercent(0.10811742248552014))   // periodo
        assertEquals("11.11%", formatPercent(0.11111742248552015))   // requerido periodo
        assertEquals("11.14%", formatPercent(0.11143910150258418))   // requerido anualizado
    }

    /**
     * Los escenarios adversos de FX ahora son bastante más grandes. Nada los
     * recorta: dos decimales completos, sin abreviar.
     */
    @Test
    fun `escenarios adversos de fx se muestran completos`() {
        assertEquals("23.46%", formatPercent(0.23457491387279994))
        assertEquals("16.96%", formatPercent(0.16959728682686315))
        assertEquals("5.82%", formatPercent(0.05820706903382855))
        assertEquals("1.01%", formatPercent(0.010106747714109021))
    }

    @Test
    fun `porcentaje sin decimales`() {
        assertEquals("0%", formatPercent(0.0, decimals = 0))
        assertEquals("-50%", formatPercent(-0.5, decimals = 0))
        assertEquals("20%", formatPercent(0.2, decimals = 0))
    }

    @Test
    fun `porcentaje con signo explicito`() {
        assertEquals("+2.88%", formatSignedPercent(0.0288))
        assertEquals("-1.44%", formatSignedPercent(-0.0144))
        assertEquals("+0.72%", formatSignedPercent(0.0072))
        assertEquals("-50%", formatSignedPercent(-0.5, decimals = 0))
        assertEquals("+100%", formatSignedPercent(1.0, decimals = 0))
        assertEquals("+0%", formatSignedPercent(0.0, decimals = 0))
        assertEquals("-10%", formatSignedPercent(-0.1, decimals = 0))
    }

    // ── Dinero ────────────────────────────────────────────────────────────

    @Test
    fun `pesos con separador de miles y sin decimales`() {
        assertEquals("43,560 MXN", formatMxn(43560.0))
        // El número dominante de la pantalla Hoy: lo que CETES paga al año.
        assertEquals("2,545 MXN", formatMxn(2545.2108))
        assertEquals("1,080 MXN", formatMxn(1080.0))
        assertEquals("360 MXN", formatMxn(360.0))
        assertEquals("0 MXN", formatMxn(0.0))
        assertEquals("128,384 MXN", formatMxn(128383.92))
    }

    @Test
    fun `pesos con decimales cuando se piden`() {
        assertEquals("1,234,567.89 MXN", formatMxn(1234567.89, decimals = 2))
        assertEquals("6.48 MXN", formatMxn(6.48, decimals = 2))
    }

    @Test
    fun `pesos con signo explicito`() {
        assertEquals("-720 MXN", formatSignedMxn(-720.0))
        assertEquals("+1,440 MXN", formatSignedMxn(1440.0))
        assertEquals("+360 MXN", formatSignedMxn(360.0))
    }

    // ── Decimales sueltos ─────────────────────────────────────────────────

    @Test
    fun `decimales y multiplicador`() {
        assertEquals("1.7", formatDecimal(1.6666666666666665))
        assertEquals("17.1387", formatDecimal(17.1387, decimals = 4))
        assertEquals("x0.30", formatMultiplier(0.3))
        assertEquals("x0.60", formatMultiplier(0.6))
    }

    @Test
    fun `redondeo half up, no half even`() {
        assertEquals("3", formatDecimal(2.5, decimals = 0))
        assertEquals("4", formatDecimal(3.5, decimals = 0))
    }

    // ── Valores imposibles ────────────────────────────────────────────────

    @Test
    fun `no finitos no se renderizan como numero`() {
        assertEquals(NO_VALUE, formatPercent(Double.NaN))
        assertEquals(NO_VALUE, formatPercent(Double.POSITIVE_INFINITY))
        assertEquals(NO_VALUE, formatMxn(Double.NEGATIVE_INFINITY))
        assertEquals(NO_VALUE, formatSignedMxn(Double.NaN))
        assertEquals(NO_VALUE, formatSignedPercent(Double.POSITIVE_INFINITY))
        assertEquals(NO_VALUE, formatDecimal(Double.NaN))
        assertEquals(NO_VALUE, formatMultiplier(Double.NaN))
    }

    // ── Fechas ────────────────────────────────────────────────────────────

    @Test
    fun `fecha ISO a formato mexicano`() {
        assertEquals("07/08/2026", formatIsoDate("2026-08-07"))
        assertEquals("10/08/2026", formatIsoDate("2026-08-10"))
        assertEquals("10/08/2026", formatSnapshotFileName("2026-08-10.json"))
    }

    @Test
    fun `fecha ilegible se devuelve tal cual`() {
        assertEquals("no-es-fecha", formatIsoDate("no-es-fecha"))
        assertNull(parseIsoDateOrNull("2026-13-45"))
    }

    @Test
    fun `generated_at con offset se formatea en la zona pedida`() {
        val iso = "2026-08-10T02:51:56.993514+00:00"
        assertEquals("10/08/2026 02:51", formatIsoDateTime(iso, ZoneOffset.UTC))
        // Ciudad de México siempre está detrás de UTC: el instante cae el día 9.
        assertEquals("09/08/2026", formatIsoInstantAsDate(iso, ZoneId.of("America/Mexico_City")))
    }

    @Test
    fun `generated_at sin offset no revienta`() {
        assertNull(parseIsoInstantOrNull("2026-08-10 02:51:56"))
        assertEquals("ayer", formatIsoDateTime("ayer", ZoneOffset.UTC))
    }

    @Test
    fun `antiguedad en dias completos`() {
        val iso = "2026-08-10T00:00:00+00:00"
        val base = Instant.parse("2026-08-10T00:00:00Z")
        assertEquals(0L, ageInDays(iso, base))
        assertEquals(0L, ageInDays(iso, base.plusSeconds(86_399)))
        assertEquals(1L, ageInDays(iso, base.plusSeconds(86_400)))
        assertEquals(4L, ageInDays(iso, base.plusSeconds(4 * 86_400)))
        assertNull(ageInDays("no-es-fecha", base))
    }
}
