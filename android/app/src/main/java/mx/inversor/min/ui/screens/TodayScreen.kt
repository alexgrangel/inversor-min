package mx.inversor.min.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import mx.inversor.min.R
import mx.inversor.min.data.MaterialityDto
import mx.inversor.min.data.SnapshotDto
import mx.inversor.min.ui.components.ActionChip
import mx.inversor.min.ui.components.BulletList
import mx.inversor.min.ui.components.Callout
import mx.inversor.min.ui.components.HeadlineNumber
import mx.inversor.min.ui.components.KeyValueRow
import mx.inversor.min.ui.components.SectionCard
import mx.inversor.min.ui.components.TableRow
import mx.inversor.min.ui.theme.ActionTone
import mx.inversor.min.ui.theme.LocalIsDarkTheme
import mx.inversor.min.ui.theme.colorsForTone
import mx.inversor.min.util.formatDecimal
import mx.inversor.min.util.formatIsoDateTime
import mx.inversor.min.util.formatMxn
import mx.inversor.min.util.formatPercent
import mx.inversor.min.util.formatSignedMxn
import mx.inversor.min.util.formatSignedPercent
import java.time.ZoneId
import kotlin.math.abs

private const val VEREDICTO_INMATERIAL = "INMATERIAL"

/** Pesos de columna de la tabla de escenarios. */
private val MATERIALITY_WEIGHTS = listOf(1.1f, 1f, 1.3f)

/** Pantalla 1: la decisión de hoy. */
@Composable
fun TodayScreen(snapshot: SnapshotDto, modifier: Modifier = Modifier) {
    val zone = remember { ZoneId.systemDefault() }
    val materiality = snapshot.sizing?.materiality
    val inmaterial = materiality?.veredicto == VEREDICTO_INMATERIAL

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        ActionChip(action = snapshot.action)

        Text(
            text = snapshot.headline,
            style = MaterialTheme.typography.titleLarge,
            color = MaterialTheme.colorScheme.onSurface,
        )

        Column {
            Text(
                text = stringResource(
                    R.string.today_generated_at,
                    formatIsoDateTime(snapshot.generatedAt, zone),
                ),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                text = stringResource(R.string.today_schema, snapshot.schemaVersion),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        if (snapshot.blockers.isNotEmpty()) {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.errorContainer,
                    contentColor = MaterialTheme.colorScheme.onErrorContainer,
                ),
            ) {
                Column(Modifier.padding(16.dp)) {
                    Text(
                        text = stringResource(R.string.today_blockers_title),
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                    )
                    Spacer(Modifier.height(8.dp))
                    snapshot.blockers.forEach { blocker ->
                        Text(text = blocker, style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }
        }

        // Cuando el sleeve es inmaterial, esa es LA noticia del día: va arriba
        // de la asignación y con el número de CETES como elemento dominante.
        // Enterrarla bajo una tabla de asignación sería el error contrario al
        // que existe esta app.
        if (inmaterial && materiality != null) {
            InmaterialCard(materiality = materiality)
        }

        // ── Asignación objetivo ───────────────────────────────────────────
        if (snapshot.allocationMxn.isNotEmpty()) {
            SectionCard(title = stringResource(R.string.card_allocation_title)) {
                TableRow(
                    cells = listOf(
                        stringResource(R.string.col_instrument),
                        stringResource(R.string.col_mxn),
                    ),
                    weights = listOf(1.6f, 1f),
                    header = true,
                )
                snapshot.allocationMxn.forEach { (instrument, amount) ->
                    TableRow(
                        cells = listOf(instrument, formatMxn(amount)),
                        weights = listOf(1.6f, 1f),
                    )
                }
                HorizontalDivider(color = MaterialTheme.colorScheme.outline)
                TableRow(
                    cells = listOf(
                        stringResource(R.string.row_total),
                        formatMxn(snapshot.allocationMxn.values.sum()),
                    ),
                    weights = listOf(1.6f, 1f),
                    emphasis = true,
                )
            }
        }

        // ── ¿Mueve la aguja? (versión normal, cuando SÍ es material) ──────
        if (materiality != null && !inmaterial) {
            MaterialCard(materiality = materiality)
        }

        // ── Costo de oportunidad (hurdle) ─────────────────────────────────
        snapshot.hurdle?.let { hurdle ->
            SectionCard(title = stringResource(R.string.card_hurdle_title)) {
                KeyValueRow(
                    label = stringResource(R.string.hurdle_cetes_nominal, hurdle.tenorDays),
                    value = formatPercent(hurdle.cetesNominal),
                )
                KeyValueRow(
                    label = stringResource(R.string.hurdle_inflation),
                    value = formatPercent(hurdle.inflacion),
                )
                KeyValueRow(
                    label = stringResource(R.string.hurdle_real_pretax),
                    value = formatPercent(hurdle.cetesRealPretax),
                )
                // Base gravable del art. 134: es una RESTA, no la relación de
                // Fisher de la fila anterior. Van juntas y etiquetadas distinto
                // justamente porque se parecen y no son lo mismo.
                KeyValueRow(
                    label = stringResource(R.string.hurdle_base_gravable),
                    value = formatPercent(hurdle.baseGravableLisr134),
                )
                KeyValueRow(
                    label = stringResource(R.string.hurdle_isr),
                    value = formatSignedPercent(-hurdle.isrSobreInteresReal),
                )
                KeyValueRow(
                    label = stringResource(R.string.hurdle_net_nominal),
                    value = formatPercent(hurdle.cetesNetoNominal),
                    emphasis = true,
                )
                KeyValueRow(
                    label = stringResource(R.string.hurdle_net_real),
                    value = formatPercent(hurdle.cetesNetoReal),
                )
                KeyValueRow(
                    label = stringResource(R.string.hurdle_risk_premium),
                    value = formatPercent(hurdle.primaDeRiesgoExigida),
                )

                Spacer(Modifier.height(14.dp))

                // Las dos tasas del hurdle, separadas visualmente. Confundirlas
                // infla el hurdle por el factor 365/horizonte.
                Callout(tone = ActionTone.BLUE) {
                    Text(
                        text = stringResource(R.string.hurdle_two_rates_title),
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = FontWeight.Bold,
                    )
                    Spacer(Modifier.height(6.dp))
                    KeyValueRow(
                        label = stringResource(R.string.hurdle_anualizado),
                        value = formatPercent(hurdle.hurdleTotalAnualizado),
                    )
                    KeyValueRow(
                        label = stringResource(R.string.hurdle_periodo, hurdle.horizonDays),
                        value = formatPercent(hurdle.hurdleTotalPeriodo),
                        emphasis = true,
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text = stringResource(R.string.hurdle_two_rates_caption),
                        style = MaterialTheme.typography.bodySmall,
                    )
                }

                snapshot.requiredReturns?.let { required ->
                    Spacer(Modifier.height(14.dp))
                    Text(
                        text = stringResource(R.string.required_title),
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    KeyValueRow(
                        label = stringResource(
                            R.string.required_periodo,
                            required.horizonDays,
                        ),
                        value = formatPercent(required.rendimientoMxnRequeridoPeriodo),
                        emphasis = true,
                    )
                    KeyValueRow(
                        label = stringResource(R.string.required_anualizado),
                        value = formatPercent(required.rendimientoMxnRequeridoAnualizado),
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text = required.explicacion,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }

                if (hurdle.assumptions.isNotEmpty()) {
                    Spacer(Modifier.height(12.dp))
                    Text(
                        text = stringResource(R.string.hurdle_assumptions),
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(6.dp))
                    BulletList(items = hurdle.assumptions)
                }
            }
        }

        // ── Presupuesto de comisiones ─────────────────────────────────────
        snapshot.costs?.let { costs ->
            SectionCard(title = stringResource(R.string.card_fees_title)) {
                KeyValueRow(
                    label = stringResource(R.string.fees_max_round_trips),
                    value = formatDecimal(costs.maxRoundTripsPerYear),
                )
                KeyValueRow(
                    label = stringResource(R.string.fees_remaining),
                    value = formatDecimal(costs.roundTripsRemaining),
                    emphasis = true,
                )
                KeyValueRow(
                    label = stringResource(R.string.fees_breakeven),
                    value = formatPercent(costs.breakevenMovePct),
                )
                costs.minNotionalCheck?.let { check ->
                    KeyValueRow(
                        label = stringResource(R.string.fees_min_notional),
                        value = check,
                    )
                }
                if (costs.budgetExhausted) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text = stringResource(R.string.fees_exhausted),
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
        }

        // ── Pie ───────────────────────────────────────────────────────────
        Spacer(Modifier.height(4.dp))
        Text(
            text = stringResource(R.string.disclaimer_engine),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = stringResource(R.string.disclaimer),
            style = MaterialTheme.typography.bodySmall,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(24.dp))
    }
}

/**
 * Veredicto INMATERIAL: la app diciéndole a su dueño lo que no quiere oír.
 * Tarjeta ámbar completa, con `cetes_anual_mxn` como número dominante de la
 * pantalla y el escenario alcista traducido a pesos.
 */
@Composable
private fun InmaterialCard(materiality: MaterialityDto) {
    val colors = colorsForTone(ActionTone.AMBER, LocalIsDarkTheme.current)
    // El escenario de referencia es el alza más cercana a +50%; se etiqueta con
    // el movimiento real de esa fila para no inventar un "+50%" que no exista.
    val upside = materiality.escenarios.minByOrNull { abs(it.movimientoCripto - 0.5) }

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = colors.container,
            contentColor = colors.content,
        ),
    ) {
        Column(Modifier.padding(18.dp)) {
            Text(
                text = stringResource(R.string.materiality_inmaterial_title),
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold,
            )
            Spacer(Modifier.height(10.dp))

            if (upside != null) {
                Text(
                    text = stringResource(
                        R.string.materiality_inmaterial_body,
                        formatSignedPercent(upside.movimientoCripto, decimals = 0),
                        formatSignedPercent(upside.impactoPortafolioPct),
                        formatSignedMxn(upside.impactoPortafolioMxn),
                    ),
                    style = MaterialTheme.typography.bodyLarge,
                )
                Spacer(Modifier.height(8.dp))
            }

            Text(
                text = stringResource(R.string.materiality_inmaterial_action),
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Bold,
            )

            Spacer(Modifier.height(14.dp))
            HorizontalDivider(color = LocalContentColor.current.copy(alpha = 0.4f))
            Spacer(Modifier.height(10.dp))

            // Elemento más legible de la pantalla.
            HeadlineNumber(
                label = stringResource(R.string.materiality_cetes_dominant),
                value = formatMxn(materiality.cetesAnualMxn),
                dominant = true,
            )

            Spacer(Modifier.height(10.dp))
            HorizontalDivider(color = LocalContentColor.current.copy(alpha = 0.4f))
            Spacer(Modifier.height(10.dp))

            MaterialityScenarioTable(materiality)
        }
    }
}

/** Versión normal, cuando el veredicto es MATERIAL. */
@Composable
private fun MaterialCard(materiality: MaterialityDto) {
    SectionCard(title = stringResource(R.string.card_materiality_title)) {
        KeyValueRow(
            label = stringResource(R.string.materiality_weight),
            value = formatPercent(materiality.pesoSobreCapitalTotal),
        )
        KeyValueRow(
            label = stringResource(R.string.materiality_verdict),
            value = materiality.veredicto,
            emphasis = true,
        )
        Spacer(Modifier.height(8.dp))
        MaterialityScenarioTable(materiality)
        Spacer(Modifier.height(10.dp))
        HorizontalDivider(color = MaterialTheme.colorScheme.outline)
        HeadlineNumber(
            label = stringResource(R.string.materiality_cetes_label),
            value = formatMxn(materiality.cetesAnualMxn),
        )
    }
}

@Composable
private fun MaterialityScenarioTable(materiality: MaterialityDto) {
    TableRow(
        cells = listOf(
            stringResource(R.string.col_if_crypto),
            stringResource(R.string.col_impact_pct),
            stringResource(R.string.col_impact_mxn),
        ),
        weights = MATERIALITY_WEIGHTS,
        header = true,
    )
    materiality.escenarios.forEach { escenario ->
        TableRow(
            cells = listOf(
                formatSignedPercent(escenario.movimientoCripto, decimals = 0),
                formatSignedPercent(escenario.impactoPortafolioPct),
                formatSignedMxn(escenario.impactoPortafolioMxn),
            ),
            weights = MATERIALITY_WEIGHTS,
        )
    }
    Spacer(Modifier.height(6.dp))
    Text(
        text = stringResource(
            R.string.materiality_sleeve_is,
            formatPercent(materiality.pesoSobreCapitalTotal),
            materiality.veredicto,
        ),
        style = MaterialTheme.typography.bodySmall,
        color = LocalContentColor.current,
    )
}
