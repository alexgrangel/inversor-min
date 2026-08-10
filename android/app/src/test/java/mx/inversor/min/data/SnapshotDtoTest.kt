package mx.inversor.min.data

import kotlinx.serialization.SerializationException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Estos tests corren contra una copia literal de snapshots/latest.json.
 *
 * El objetivo no es "el parser corre": es que si el engine renombra o quita un
 * campo, esto truene en CI antes de que la app muestre un cero inventado.
 */
class SnapshotDtoTest {

    private fun rawJson(): String =
        checkNotNull(javaClass.getResourceAsStream("/latest.json")) {
            "Falta app/src/test/resources/latest.json (copia de snapshots/latest.json)."
        }.bufferedReader(Charsets.UTF_8).use { it.readText() }

    private fun parsed(): SnapshotDto = SnapshotParser.parse(rawJson())

    // ── Identidad de la decisión ──────────────────────────────────────────

    @Test
    fun `campos de identidad`() {
        val d = parsed()
        assertEquals("1.0.0", d.schemaVersion)
        assertEquals("2026-08-10T03:28:01.658146+00:00", d.generatedAt)
        assertEquals("ALLOCATE_TO_CRYPTO", d.action)
        assertTrue(d.headline.startsWith("Aumentar sleeve cripto en 1,440 MXN"))
    }

    @Test
    fun `listas de razonamiento`() {
        val d = parsed()
        assertEquals(13, d.reasons.size)
        assertTrue(d.reasons[0].startsWith("Hurdle: CETES 364d"))
        assertEquals(0, d.blockers.size)
        assertEquals(2, d.warnings.size)
        assertTrue(d.warnings[0].startsWith("Sleeve de 1,440 MXN"))
        assertTrue(d.warnings[1].startsWith("Tienes ingresos y gastos en MXN"))
    }

    /**
     * Un renombrado de SECCIÓN de nivel superior no puede detectarse por tipos
     * (las secciones son nullable para tolerar los `{}` del engine), así que se
     * detecta aquí.
     */
    @Test
    fun `todas las secciones de nivel superior estan presentes`() {
        val d = parsed()
        assertNotNull(d.market)
        assertNotNull(d.hurdle)
        assertNotNull(d.sizing)
        assertNotNull(d.sizing?.materiality)
        assertNotNull(d.costs)
        assertNotNull(d.requiredReturns)
        assertNotNull(d.fx)
        assertNotNull(d.policy)
        assertFalse(d.allocationMxn.isEmpty())
        assertFalse(d.dataFreshness.isEmpty())
    }

    // ── market ────────────────────────────────────────────────────────────

    @Test
    fun `market`() {
        val m = requireNotNull(parsed().market)
        assertEquals(17.1387, m.usdmxnFix, 0.0)
        assertEquals("2026-08-07", m.usdmxnFixAsOf)
        assertEquals(0.031200000000000002, m.inflacionAnual, 0.0)
        assertEquals(0.065, requireNotNull(m.tasaObjetivo), 0.0)
        assertEquals(listOf("28", "91", "182", "364"), m.cetesCurve.keys.toList())
        assertEquals(0.0701, requireNotNull(m.cetesCurve["364"]), 0.0)
        assertEquals(0.0617, requireNotNull(m.cetesCurve["28"]), 0.0)
    }

    // ── hurdle ────────────────────────────────────────────────────────────

    @Test
    fun `hurdle`() {
        val h = requireNotNull(parsed().hurdle)
        assertEquals(364, h.tenorDays)
        assertEquals(364, h.horizonDays)
        assertEquals(0.0701, h.cetesNominal, 0.0)
        assertEquals(0.031200000000000002, h.inflacion, 0.0)
        assertEquals(0.037723041117145195, h.cetesRealPretax, 0.0)
        assertEquals(0.03889999999999999, h.baseGravableLisr134, 0.0)
        assertEquals(0.011669999999999996, h.isrSobreInteresReal, 0.0)
        assertEquals(0.058429999999999996, h.cetesNetoNominal, 0.0)
        assertEquals(0.02640612878200166, h.cetesNetoReal, 0.0)
        assertEquals(0.05, h.primaDeRiesgoExigida, 0.0)
        assertEquals(0.10843, h.hurdleTotalAnualizado, 0.0)
        assertEquals(0.10811742248552014, h.hurdleTotalPeriodo, 0.0)
        assertEquals(3, h.assumptions.size)
    }

    /**
     * La confusión que este contrato existe para evitar: presentar una tasa
     * anualizada como si fuera el rendimiento requerido en el periodo. A 28
     * días eso infla el hurdle ~13x. Son dos campos y se leen por separado.
     */
    @Test
    fun `las dos tasas del hurdle son campos distintos`() {
        val h = requireNotNull(parsed().hurdle)
        assertNotEquals(h.hurdleTotalAnualizado, h.hurdleTotalPeriodo, 1e-12)
        // La base gravable del art. 134 es una resta; la de Fisher es un
        // cociente. Nunca deben mapearse al mismo campo.
        assertNotEquals(h.cetesRealPretax, h.baseGravableLisr134, 1e-12)
    }

    // ── sizing / regimes / materiality ────────────────────────────────────

    @Test
    fun `sizing`() {
        val s = requireNotNull(parsed().sizing)
        assertEquals(0.032, s.weight, 0.0)
        assertEquals(1440.0, s.weightMxn, 0.0)
        assertEquals("regime_multiplier(0.30)", s.bindingConstraint)
        assertEquals(0.15542077887274125, s.volTargetWeight, 0.0)
        assertEquals(0.10666666666666667, s.drawdownBudgetWeight, 0.0)
        assertEquals(0.2, s.hardCapWeight, 0.0)
        assertEquals(0.5147316889043781, s.realizedVolAnnual, 0.0)
        assertEquals(0.0164714140449401, s.impliedPortfolioVol, 0.0)
        assertEquals(1080.0, s.impliedWorstCaseLossMxn, 0.0)
        assertEquals(6, s.notes.size)
        assertEquals(0.3, s.regimeMultiplier, 0.0)
    }

    @Test
    fun `regimes`() {
        val regimes = requireNotNull(parsed().sizing).regimes
        assertEquals(2, regimes.size)

        val neutral = regimes[0]
        assertEquals("NEUTRAL", neutral.label)
        assertEquals(0.6, neutral.sizeMultiplier, 0.0)
        assertEquals(104053.67500044397, neutral.price, 0.0)
        assertEquals(116642.58489643037, neutral.sma200, 0.0)
        assertEquals(117216.49872954245, neutral.sma50, 0.0)
        assertEquals(-0.1079272197813893, neutral.pctFrom200, 0.0)
        assertEquals(-0.3294096288283719, neutral.drawdownFrom1yHigh, 0.0)
        assertEquals(0.4744991990674987, neutral.vol30d, 0.0)
        assertEquals(0.6170212765957447, neutral.volPercentile2y, 0.0)
        assertEquals(5, neutral.signals.size)

        val riskOff = regimes[1]
        assertEquals("RISK_OFF", riskOff.label)
        assertEquals(0.3, riskOff.sizeMultiplier, 0.0)
        assertEquals(6, riskOff.signals.size)
    }

    @Test
    fun `materiality`() {
        val m = requireNotNull(requireNotNull(parsed().sizing).materiality)
        assertEquals(0.0288, m.pesoSobreCapitalTotal, 0.0)
        assertEquals("INMATERIAL", m.veredicto)
        assertEquals(2545.2108, m.cetesAnualMxn, 0.0)
        assertEquals(5, m.escenarios.size)

        assertEquals(-0.5, m.escenarios[0].movimientoCripto, 0.0)
        assertEquals(-0.0144, m.escenarios[0].impactoPortafolioPct, 0.0)
        assertEquals(-720.0, m.escenarios[0].impactoPortafolioMxn, 0.0)

        assertEquals(0.5, m.escenarios[3].movimientoCripto, 0.0)
        assertEquals(0.0144, m.escenarios[3].impactoPortafolioPct, 0.0)
        assertEquals(720.0, m.escenarios[3].impactoPortafolioMxn, 0.0)

        assertEquals(1.0, m.escenarios[4].movimientoCripto, 0.0)
        assertEquals(0.0288, m.escenarios[4].impactoPortafolioPct, 0.0)
        assertEquals(1440.0, m.escenarios[4].impactoPortafolioMxn, 0.0)
    }

    /**
     * El veredicto maneja la rama prominente de TodayScreen. Si el engine
     * empieza a mandar otra cadena, el test lo enseña en vez de dejar la app
     * cayendo silenciosamente en el camino "material".
     */
    @Test
    fun `veredicto de materialidad es una de las dos cadenas conocidas`() {
        val veredicto = requireNotNull(requireNotNull(parsed().sizing).materiality).veredicto
        assertTrue(veredicto in setOf("MATERIAL", "INMATERIAL"))
    }

    // ── costs ─────────────────────────────────────────────────────────────

    @Test
    fun `costs`() {
        val c = requireNotNull(parsed().costs)
        assertEquals(50000.0, c.capitalMxn, 0.0)
        assertEquals(7.2, c.annualBudgetMxn, 0.0)
        assertEquals(0.003, c.costPerRoundTripPct, 0.0)
        assertEquals(4.32, c.costPerRoundTripMxn, 0.0)
        assertEquals(1.6666666666666665, c.maxRoundTripsPerYear, 0.0)
        assertEquals(1.6666666666666665, c.roundTripsRemaining, 0.0)
        assertEquals(0.0, c.feesSpentYtdMxn, 0.0)
        assertFalse(c.budgetExhausted)
        assertEquals(0.003, c.breakevenMovePct, 0.0)
        assertEquals(4, c.notes.size)
        assertEquals(
            "Pata más chica: 21.01 USD vs mínimo 10.00 USD (OK).",
            c.minNotionalCheck,
        )
    }

    // ── allocation ────────────────────────────────────────────────────────

    @Test
    fun `allocation conserva el orden del engine`() {
        val a = parsed().allocationMxn
        assertEquals(
            listOf("reserva_liquidez", "BTCUSDT", "ETHUSDT", "CETES_364d"),
            a.keys.toList(),
        )
        assertEquals(5000.0, requireNotNull(a["reserva_liquidez"]), 0.0)
        assertEquals(1080.0, requireNotNull(a["BTCUSDT"]), 0.0)
        assertEquals(360.0, requireNotNull(a["ETHUSDT"]), 0.0)
        assertEquals(43560.0, requireNotNull(a["CETES_364d"]), 0.0)
        assertEquals(50000.0, a.values.sum(), 1e-9)
    }

    // ── required_returns ──────────────────────────────────────────────────

    @Test
    fun `required returns`() {
        val r = requireNotNull(parsed().requiredReturns)
        assertEquals(0.10811742248552014, r.hurdlePeriodo, 0.0)
        assertEquals(0.10843, r.hurdleAnualizado, 0.0)
        assertEquals(364, r.horizonDays)
        assertEquals(0.003, r.feeDragRoundTrip, 0.0)
        assertEquals(0.0, r.isrEfectivoCripto, 0.0)
        assertEquals(0.11111742248552015, r.rendimientoMxnRequeridoPeriodo, 0.0)
        assertEquals(0.11143910150258418, r.rendimientoMxnRequeridoAnualizado, 0.0)
        assertTrue(r.isrNota.startsWith("Ganancia esperada"))
        assertTrue(r.explicacion.contains("EN PESOS"))
    }

    @Test
    fun `el requerido de periodo y el anualizado son campos distintos`() {
        val r = requireNotNull(parsed().requiredReturns)
        assertNotEquals(
            r.rendimientoMxnRequeridoPeriodo,
            r.rendimientoMxnRequeridoAnualizado,
            1e-12,
        )
        assertNotEquals(r.hurdlePeriodo, r.hurdleAnualizado, 1e-12)
        // El horizonte del bloque de required_returns tiene que coincidir con
        // el del hurdle: la UI etiqueta las filas con estos días.
        assertEquals(requireNotNull(parsed().hurdle).horizonDays, r.horizonDays)
    }

    // ── fx ────────────────────────────────────────────────────────────────

    @Test
    fun `fx`() {
        val fx = requireNotNull(parsed().fx)
        assertEquals(17.1387, fx.usdmxnFix, 0.0)
        assertEquals(5, fx.sensibilidad.size)
        assertEquals(-0.1, fx.sensibilidad[0].escenarioMxn, 0.0)
        assertEquals(0.23457491387279994, fx.sensibilidad[0].rendimientoUsdRequerido, 0.0)
        assertEquals(-0.05, fx.sensibilidad[1].escenarioMxn, 0.0)
        assertEquals(0.16959728682686315, fx.sensibilidad[1].rendimientoUsdRequerido, 0.0)
        assertEquals(0.0, fx.sensibilidad[2].escenarioMxn, 0.0)
        assertEquals(0.11111742248552003, fx.sensibilidad[2].rendimientoUsdRequerido, 0.0)
        assertEquals(0.1, fx.sensibilidad[4].escenarioMxn, 0.0)
        assertEquals(0.010106747714109021, fx.sensibilidad[4].rendimientoUsdRequerido, 0.0)
        assertTrue(fx.advertencia.contains("larga en USD"))
    }

    /**
     * La sensibilidad ya no es una resta. El escenario adverso tiene que ser
     * estrictamente mayor que "requerido + apreciación", que es lo que daba el
     * cálculo lineal viejo. Si alguien regresa a la resta, esto truena.
     */
    @Test
    fun `los escenarios adversos de fx son multiplicativos, no una resta`() {
        val fx = requireNotNull(parsed().fx)
        val base = fx.sensibilidad.first { it.escenarioMxn == 0.0 }.rendimientoUsdRequerido
        val adverso = fx.sensibilidad.first { it.escenarioMxn == -0.1 }
        val lineal = base - adverso.escenarioMxn   // el viejo: base + 0.10
        assertTrue(
            "El escenario adverso ($adverso) debería superar al lineal ($lineal)",
            adverso.rendimientoUsdRequerido > lineal,
        )
    }

    // ── data_freshness ────────────────────────────────────────────────────

    @Test
    fun `data freshness`() {
        val df = parsed().dataFreshness
        assertEquals(
            setOf(
                "fix_usdmxn", "cetes_28", "cetes_91", "cetes_182",
                "cetes_364", "tasa_objetivo", "inpc_anual",
            ),
            df.keys,
        )
        val c364 = requireNotNull(df["cetes_364"])
        assertEquals("REAL", c364.seriesId)
        assertEquals(7.01, c364.value, 0.0)
        assertEquals("2026-08-07", c364.asOf)
        assertEquals(3, c364.staleDays)
        assertFalse(c364.stale)
        assertEquals(3.12, requireNotNull(df["inpc_anual"]).value, 0.0)
        assertTrue(df.values.none { it.stale })
    }

    // ── policy ────────────────────────────────────────────────────────────

    @Test
    fun `policy`() {
        val p = requireNotNull(parsed().policy)
        assertEquals(50000.0, p.portfolio.totalCapitalMxn, 0.0)
        assertEquals(364, p.portfolio.horizonDays)
        assertEquals(5000.0, p.portfolio.liquidityReserveMxn, 0.0)

        assertEquals(0.3, p.tax.marginalIsrRate, 0.0)
        assertEquals(0.009, p.tax.retencionProvisionalAnual, 0.0)
        assertEquals(128383.92, p.tax.exencionAnualBienesMueblesMxn, 0.0)
        assertEquals(0.0, p.tax.gananciasCriptoYtdMxn, 0.0)

        assertEquals(0.08, p.risk.maxPortfolioDrawdownFromCrypto, 0.0)
        assertEquals(0.75, p.risk.assumedCryptoMaxDrawdown, 0.0)
        assertEquals(0.08, p.risk.cryptoVolTarget, 0.0)
        assertEquals(0.2, p.risk.maxCryptoWeight, 0.0)
        assertEquals(0.03, p.risk.minCryptoWeight, 0.0)

        assertEquals(0.005, p.cost.annualFeeBudgetPct, 0.0)
        assertEquals(0.001, p.cost.takerFeePct, 0.0)
        assertEquals(0.0005, p.cost.slippagePct, 0.0)
        assertEquals(10.0, p.cost.minNotionalUsd, 0.0)
        assertEquals(0.0, p.cost.feesSpentYtdMxn, 0.0)

        assertEquals(listOf("BTCUSDT", "ETHUSDT"), p.universe.cryptoSymbols)
        assertEquals(listOf(0.75, 0.25), p.universe.cryptoWeights)

        assertEquals(0.05, p.requiredRiskPremium, 0.0)
        assertEquals(5, p.maxStalenessDays)
    }

    // ── Rupturas de esquema: tienen que TRONAR ────────────────────────────

    @Test
    fun `renombrar un campo obligatorio truena`() {
        val broken = rawJson().replace("\"cetes_neto_nominal\"", "\"cetes_neto\"")
        assertThrows(SerializationException::class.java) { SnapshotParser.parse(broken) }
    }

    @Test
    fun `quitar la accion truena`() {
        val broken = rawJson().replace("\"action\": \"ALLOCATE_TO_CRYPTO\",", "")
        assertThrows(SerializationException::class.java) { SnapshotParser.parse(broken) }
    }

    @Test
    fun `renombrar un campo dentro de una lista truena`() {
        val broken = rawJson().replace("\"movimiento_cripto\"", "\"mov_cripto\"")
        assertThrows(SerializationException::class.java) { SnapshotParser.parse(broken) }
    }

    @Test
    fun `renombrar un campo de data_freshness truena`() {
        val broken = rawJson().replace("\"stale_days\"", "\"dias_rancio\"")
        assertThrows(SerializationException::class.java) { SnapshotParser.parse(broken) }
    }

    @Test
    fun `renombrar un campo de policy truena`() {
        val broken = rawJson().replace("\"max_crypto_weight\"", "\"tope_cripto\"")
        assertThrows(SerializationException::class.java) { SnapshotParser.parse(broken) }
    }

    /**
     * Volver al esquema viejo (un solo `hurdle_total`) tiene que tronar, no
     * degradarse a mostrar la tasa anualizada como si fuera la del periodo.
     */
    @Test
    fun `regresar al hurdle_total viejo truena`() {
        val old = rawJson().replace("\"hurdle_total_periodo\"", "\"hurdle_total\"")
        assertThrows(SerializationException::class.java) { SnapshotParser.parse(old) }

        val old2 = rawJson().replace("\"hurdle_total_anualizado\"", "\"hurdle_total\"")
        assertThrows(SerializationException::class.java) { SnapshotParser.parse(old2) }
    }

    @Test
    fun `quitar horizon_days truena`() {
        // Aparece en hurdle, en required_returns y en policy.portfolio.
        val broken = rawJson().replace("\"horizon_days\"", "\"dias_horizonte\"")
        assertThrows(SerializationException::class.java) { SnapshotParser.parse(broken) }
    }

    @Test
    fun `quitar base_gravable_lisr134 truena`() {
        val broken = rawJson().replace("\"base_gravable_lisr134\"", "\"base_gravable\"")
        assertThrows(SerializationException::class.java) { SnapshotParser.parse(broken) }
    }

    @Test
    fun `renombrar el rendimiento requerido de periodo truena`() {
        val broken = rawJson()
            .replace("\"rendimiento_mxn_requerido_periodo\"", "\"rendimiento_mxn_requerido\"")
        assertThrows(SerializationException::class.java) { SnapshotParser.parse(broken) }
    }

    @Test
    fun `una respuesta que no es un objeto JSON truena, no crashea`() {
        assertThrows(SerializationException::class.java) { SnapshotParser.parse("[]") }
        assertThrows(SerializationException::class.java) { SnapshotParser.parse("<html>404</html>") }
        assertThrows(SerializationException::class.java) { SnapshotParser.parse("") }
    }

    // ── Tolerancias explícitas ────────────────────────────────────────────

    @Test
    fun `campos nuevos del engine no rompen la app`() {
        val extended = rawJson().replaceFirst(
            "\"schema_version\": \"1.0.0\",",
            "\"schema_version\": \"1.0.0\", \"campo_nuevo\": {\"a\": 1}, \"otro\": [1,2,3],",
        )
        assertEquals("ALLOCATE_TO_CRYPTO", SnapshotParser.parse(extended).action)
    }

    @Test
    fun `secciones vacias del engine quedan en null, no en ceros`() {
        val blocked = """
            {
              "schema_version": "1.0.0",
              "generated_at": "2026-08-10T03:28:01.658146+00:00",
              "action": "BLOCKED_STALE_DATA",
              "headline": "Datos rancios. No se emite recomendación.",
              "reasons": [],
              "blockers": ["cetes_364: 9 días de antigüedad (límite 5)."],
              "warnings": [],
              "market": {},
              "hurdle": {},
              "sizing": {},
              "costs": {},
              "allocation_mxn": {},
              "required_returns": {},
              "fx": {},
              "data_freshness": {},
              "policy": {}
            }
        """.trimIndent()

        val d = SnapshotParser.parse(blocked)
        assertEquals("BLOCKED_STALE_DATA", d.action)
        assertNull(d.market)
        assertNull(d.hurdle)
        assertNull(d.sizing)
        assertNull(d.costs)
        assertNull(d.requiredReturns)
        assertNull(d.fx)
        assertNull(d.policy)
        assertTrue(d.allocationMxn.isEmpty())
        assertTrue(d.dataFreshness.isEmpty())
        assertEquals(1, d.blockers.size)
    }

    @Test
    fun `tasa_objetivo puede venir nula`() {
        val sinTasa = rawJson().replace("\"tasa_objetivo\": 0.065,", "\"tasa_objetivo\": null,")
        assertNull(requireNotNull(SnapshotParser.parse(sinTasa).market).tasaObjetivo)
    }

    // ── Índice de GitHub ──────────────────────────────────────────────────

    @Test
    fun `contents api ignora campos no usados`() {
        val raw = """
            [
              {"name":"2026-08-09.json","path":"snapshots/2026-08-09.json","sha":"abc",
               "size":10462,"type":"file",
               "download_url":"https://raw.githubusercontent.com/o/r/main/snapshots/2026-08-09.json",
               "html_url":"https://github.com/o/r/blob/main/snapshots/2026-08-09.json"},
              {"name":"latest.md","path":"snapshots/latest.md","sha":"def","size":3230,
               "type":"file","download_url":"https://example.invalid/latest.md"}
            ]
        """.trimIndent()
        val items = SnapshotParser.parseContents(raw)
        assertEquals(2, items.size)
        assertEquals("2026-08-09.json", items[0].name)
        assertEquals("file", items[0].type)
        assertTrue(requireNotNull(items[0].downloadUrl).endsWith("2026-08-09.json"))
    }
}
