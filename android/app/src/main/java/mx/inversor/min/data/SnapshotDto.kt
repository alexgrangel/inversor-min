package mx.inversor.min.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject

/**
 * Espejo exacto de `snapshots/latest.json` (engine: inversor.decide.Decision).
 *
 * Reglas de contrato:
 *  - Los nombres de campo del JSON son los que manda el engine (español incluido);
 *    aquí se mapean con @SerialName y NUNCA se renombran del lado del JSON.
 *  - Campos obligatorios (sin default): identifican la decisión. Si el engine los
 *    renombra o los quita, el parseo TRUENA. Eso es intencional: mejor pantalla de
 *    error que un número equivocado.
 *  - Las secciones de nivel superior son nullable porque el engine emite `{}` en
 *    las rutas de retorno temprano (p. ej. BLOCKED_STALE_DATA sin sizing).
 *    Ver [SnapshotParser.dropEmptySections].
 *  - Dentro de cada sección presente, los campos SÍ son obligatorios.
 */
@Serializable
data class SnapshotDto(
    @SerialName("schema_version") val schemaVersion: String,
    @SerialName("generated_at") val generatedAt: String,
    val action: String,
    val headline: String,
    val reasons: List<String> = emptyList(),
    val blockers: List<String> = emptyList(),
    val warnings: List<String> = emptyList(),
    val market: MarketDto? = null,
    val hurdle: HurdleDto? = null,
    val sizing: SizingDto? = null,
    val costs: CostsDto? = null,
    // Claves dinámicas: "reserva_liquidez", "BTCUSDT", "ETHUSDT", "CETES_364d".
    // El orden de inserción del JSON se conserva (LinkedHashMap).
    @SerialName("allocation_mxn") val allocationMxn: Map<String, Double> = emptyMap(),
    @SerialName("required_returns") val requiredReturns: RequiredReturnsDto? = null,
    val fx: FxDto? = null,
    // Claves dinámicas: "fix_usdmxn", "cetes_28", ..., "inpc_anual".
    @SerialName("data_freshness") val dataFreshness: Map<String, FreshnessDto> = emptyMap(),
    val policy: PolicyDto? = null,
)

@Serializable
data class MarketDto(
    @SerialName("usdmxn_fix") val usdmxnFix: Double,
    @SerialName("usdmxn_fix_as_of") val usdmxnFixAsOf: String,
    @SerialName("inflacion_anual") val inflacionAnual: Double,
    // El engine escribe null si no hay serie de tasa objetivo.
    @SerialName("tasa_objetivo") val tasaObjetivo: Double? = null,
    // Claves: "28", "91", "182", "364" (días).
    @SerialName("cetes_curve") val cetesCurve: Map<String, Double> = emptyMap(),
)

/**
 * Costo de oportunidad.
 *
 * Ojo con las DOS tasas: `hurdle_total_anualizado` es una tasa por año y
 * `hurdle_total_periodo` es lo que hay que ganar en `horizon_days` días.
 * Presentar la anualizada como si fuera la del periodo infla el hurdle (a 28
 * días, por 13x). Nunca se muestran sin etiqueta que las distinga.
 */
@Serializable
data class HurdleDto(
    @SerialName("tenor_days") val tenorDays: Int,
    @SerialName("horizon_days") val horizonDays: Int,
    @SerialName("cetes_nominal") val cetesNominal: Double,
    val inflacion: Double,
    /** Tasa real por Fisher: (1+nominal)/(1+inflación) − 1. */
    @SerialName("cetes_real_pretax") val cetesRealPretax: Double,
    /** Base gravable del art. 134 LISR: resta simple nominal − inflación. */
    @SerialName("base_gravable_lisr134") val baseGravableLisr134: Double,
    @SerialName("isr_sobre_interes_real") val isrSobreInteresReal: Double,
    @SerialName("cetes_neto_nominal") val cetesNetoNominal: Double,
    @SerialName("cetes_neto_real") val cetesNetoReal: Double,
    @SerialName("prima_de_riesgo_exigida") val primaDeRiesgoExigida: Double,
    @SerialName("hurdle_total_anualizado") val hurdleTotalAnualizado: Double,
    @SerialName("hurdle_total_periodo") val hurdleTotalPeriodo: Double,
    val assumptions: List<String> = emptyList(),
)

@Serializable
data class SizingDto(
    val weight: Double,
    @SerialName("weight_mxn") val weightMxn: Double,
    @SerialName("binding_constraint") val bindingConstraint: String,
    @SerialName("vol_target_weight") val volTargetWeight: Double,
    @SerialName("drawdown_budget_weight") val drawdownBudgetWeight: Double,
    @SerialName("hard_cap_weight") val hardCapWeight: Double,
    @SerialName("realized_vol_annual") val realizedVolAnnual: Double,
    @SerialName("implied_portfolio_vol") val impliedPortfolioVol: Double,
    @SerialName("implied_worst_case_loss_mxn") val impliedWorstCaseLossMxn: Double,
    val notes: List<String> = emptyList(),
    @SerialName("regime_multiplier") val regimeMultiplier: Double,
    val regimes: List<RegimeDto> = emptyList(),
    // Sólo existe cuando la decisión llegó al paso 5b del engine.
    val materiality: MaterialityDto? = null,
)

@Serializable
data class RegimeDto(
    val label: String,
    @SerialName("size_multiplier") val sizeMultiplier: Double,
    val price: Double,
    @SerialName("sma_200") val sma200: Double,
    @SerialName("sma_50") val sma50: Double,
    @SerialName("pct_from_200") val pctFrom200: Double,
    @SerialName("drawdown_from_1y_high") val drawdownFrom1yHigh: Double,
    @SerialName("vol_30d") val vol30d: Double,
    @SerialName("vol_percentile_2y") val volPercentile2y: Double,
    val signals: List<String> = emptyList(),
)

@Serializable
data class MaterialityDto(
    @SerialName("peso_sobre_capital_total") val pesoSobreCapitalTotal: Double,
    val escenarios: List<EscenarioDto> = emptyList(),
    @SerialName("cetes_anual_mxn") val cetesAnualMxn: Double,
    val veredicto: String,
)

@Serializable
data class EscenarioDto(
    @SerialName("movimiento_cripto") val movimientoCripto: Double,
    @SerialName("impacto_portafolio_pct") val impactoPortafolioPct: Double,
    @SerialName("impacto_portafolio_mxn") val impactoPortafolioMxn: Double,
)

@Serializable
data class CostsDto(
    @SerialName("capital_mxn") val capitalMxn: Double,
    @SerialName("annual_budget_mxn") val annualBudgetMxn: Double,
    @SerialName("cost_per_round_trip_pct") val costPerRoundTripPct: Double,
    @SerialName("cost_per_round_trip_mxn") val costPerRoundTripMxn: Double,
    @SerialName("max_round_trips_per_year") val maxRoundTripsPerYear: Double,
    @SerialName("round_trips_remaining") val roundTripsRemaining: Double,
    @SerialName("fees_spent_ytd_mxn") val feesSpentYtdMxn: Double,
    @SerialName("budget_exhausted") val budgetExhausted: Boolean,
    @SerialName("breakeven_move_pct") val breakevenMovePct: Double,
    val notes: List<String> = emptyList(),
    // El engine sólo lo agrega cuando llegó a evaluar el mínimo del venue.
    @SerialName("min_notional_check") val minNotionalCheck: String? = null,
)

/** Misma advertencia que en [HurdleDto]: periodo y anualizado no son lo mismo. */
@Serializable
data class RequiredReturnsDto(
    @SerialName("hurdle_periodo") val hurdlePeriodo: Double,
    @SerialName("hurdle_anualizado") val hurdleAnualizado: Double,
    @SerialName("horizon_days") val horizonDays: Int,
    @SerialName("fee_drag_round_trip") val feeDragRoundTrip: Double,
    @SerialName("isr_efectivo_cripto") val isrEfectivoCripto: Double,
    @SerialName("isr_nota") val isrNota: String,
    @SerialName("rendimiento_mxn_requerido_periodo")
    val rendimientoMxnRequeridoPeriodo: Double,
    @SerialName("rendimiento_mxn_requerido_anualizado")
    val rendimientoMxnRequeridoAnualizado: Double,
    val explicacion: String,
)

@Serializable
data class FxDto(
    @SerialName("usdmxn_fix") val usdmxnFix: Double,
    val sensibilidad: List<FxSensibilidadDto> = emptyList(),
    val advertencia: String,
)

@Serializable
data class FxSensibilidadDto(
    @SerialName("escenario_mxn") val escenarioMxn: Double,
    @SerialName("rendimiento_usd_requerido") val rendimientoUsdRequerido: Double,
    val nota: String,
)

@Serializable
data class FreshnessDto(
    @SerialName("series_id") val seriesId: String,
    val value: Double,
    @SerialName("as_of") val asOf: String,
    @SerialName("stale_days") val staleDays: Int,
    val stale: Boolean,
)

@Serializable
data class PolicyDto(
    val portfolio: PolicyPortfolioDto,
    val tax: PolicyTaxDto,
    val risk: PolicyRiskDto,
    val cost: PolicyCostDto,
    val universe: PolicyUniverseDto,
    @SerialName("required_risk_premium") val requiredRiskPremium: Double,
    @SerialName("max_staleness_days") val maxStalenessDays: Int,
)

@Serializable
data class PolicyPortfolioDto(
    @SerialName("total_capital_mxn") val totalCapitalMxn: Double,
    @SerialName("horizon_days") val horizonDays: Int,
    @SerialName("liquidity_reserve_mxn") val liquidityReserveMxn: Double,
)

@Serializable
data class PolicyTaxDto(
    @SerialName("marginal_isr_rate") val marginalIsrRate: Double,
    @SerialName("retencion_provisional_anual") val retencionProvisionalAnual: Double,
    @SerialName("exencion_anual_bienes_muebles_mxn") val exencionAnualBienesMueblesMxn: Double,
    @SerialName("ganancias_cripto_ytd_mxn") val gananciasCriptoYtdMxn: Double,
)

@Serializable
data class PolicyRiskDto(
    @SerialName("max_portfolio_drawdown_from_crypto") val maxPortfolioDrawdownFromCrypto: Double,
    @SerialName("assumed_crypto_max_drawdown") val assumedCryptoMaxDrawdown: Double,
    @SerialName("crypto_vol_target") val cryptoVolTarget: Double,
    @SerialName("max_crypto_weight") val maxCryptoWeight: Double,
    @SerialName("min_crypto_weight") val minCryptoWeight: Double,
)

@Serializable
data class PolicyCostDto(
    @SerialName("annual_fee_budget_pct") val annualFeeBudgetPct: Double,
    @SerialName("taker_fee_pct") val takerFeePct: Double,
    @SerialName("slippage_pct") val slippagePct: Double,
    @SerialName("min_notional_usd") val minNotionalUsd: Double,
    @SerialName("fees_spent_ytd_mxn") val feesSpentYtdMxn: Double,
)

@Serializable
data class PolicyUniverseDto(
    @SerialName("crypto_symbols") val cryptoSymbols: List<String> = emptyList(),
    @SerialName("crypto_weights") val cryptoWeights: List<Double> = emptyList(),
)

/** Entrada del GitHub contents API. Sólo se leen cuatro campos de muchos. */
@Serializable
data class GitHubContentDto(
    val name: String,
    val path: String,
    val type: String,
    @SerialName("download_url") val downloadUrl: String? = null,
)

object SnapshotParser {

    val json: Json = Json {
        // Campos nuevos del engine no rompen la app (regla del contrato).
        ignoreUnknownKeys = true
        // Campos requeridos ausentes SÍ truenan: no hay coerceInputValues.
        coerceInputValues = false
        isLenient = false
        // `rendimiento_mxn_requerido` puede ser Infinity si isr_efectivo == 1.
        allowSpecialFloatingPointValues = true
    }

    /**
     * El engine serializa dataclasses con `asdict`, así que las secciones que
     * nunca se llenaron aparecen como `{}` en vez de ausentes. Un `{}` no puede
     * decodificarse a una sección con campos obligatorios, y tampoco queremos
     * darle defaults a esos campos (renderizaría ceros inventados). Se eliminan
     * antes de decodificar para que la sección quede en null y la UI la omita.
     */
    fun dropEmptySections(root: JsonObject): JsonObject =
        JsonObject(root.filterNot { (_, v) -> v is JsonObject && v.isEmpty() })

    fun parse(raw: String): SnapshotDto {
        // Si la respuesta no es un objeto JSON (página de error, lista, texto),
        // se convierte en SerializationException para que la capa de arriba la
        // trate como "esquema equivocado" y no como un crash.
        val root = json.parseToJsonElement(raw) as? JsonObject
            ?: throw SerializationException("La raíz del snapshot no es un objeto JSON.")
        return json.decodeFromJsonElement(SnapshotDto.serializer(), dropEmptySections(root))
    }

    fun parseContents(raw: String): List<GitHubContentDto> =
        json.decodeFromString(ListSerializer(GitHubContentDto.serializer()), raw)
}
