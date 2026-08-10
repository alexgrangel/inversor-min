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
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import mx.inversor.min.R
import mx.inversor.min.data.SnapshotDto
import mx.inversor.min.ui.components.BulletList
import mx.inversor.min.ui.components.KeyValueRow
import mx.inversor.min.ui.components.SectionCard
import mx.inversor.min.ui.components.TableRow
import mx.inversor.min.util.formatDecimal
import mx.inversor.min.util.formatPercent
import mx.inversor.min.util.formatSignedPercent

/**
 * Pesos de la tabla de FX. La columna del rendimiento requerido se lleva más
 * espacio porque los escenarios adversos producen números de más dígitos.
 */
private val FX_WEIGHTS = listOf(1f, 1.4f)

/** Pantalla 2: el razonamiento completo, sin resumir. */
@Composable
fun WhyScreen(snapshot: SnapshotDto, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
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
                        text = stringResource(R.string.why_blockers_title),
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                    )
                    Spacer(Modifier.height(8.dp))
                    snapshot.blockers.forEach { blocker ->
                        Text(text = blocker, style = MaterialTheme.typography.bodyMedium)
                        Spacer(Modifier.height(6.dp))
                    }
                }
            }
        }

        SectionCard(title = stringResource(R.string.why_reasons_title)) {
            BulletList(
                items = snapshot.reasons,
                emptyText = stringResource(R.string.why_empty_section),
            )
        }

        SectionCard(title = stringResource(R.string.why_warnings_title)) {
            BulletList(
                items = snapshot.warnings,
                emptyText = stringResource(R.string.why_empty_section),
            )
        }

        // ── Sensibilidad al tipo de cambio ────────────────────────────────
        // El engine calcula esto de forma multiplicativa, así que los escenarios
        // adversos (peso que se aprecia) son bastante más grandes que el
        // requerido base. Se muestran con el mismo número de decimales que los
        // demás y sin maxLines: nada aquí se recorta ni se redondea a la baja.
        snapshot.fx?.let { fx ->
            SectionCard(title = stringResource(R.string.why_fx_title)) {
                KeyValueRow(
                    label = stringResource(R.string.why_fx_rate),
                    value = formatDecimal(fx.usdmxnFix, decimals = 4),
                )
                Spacer(Modifier.height(8.dp))
                TableRow(
                    cells = listOf(
                        stringResource(R.string.col_fx_scenario),
                        stringResource(R.string.col_fx_required),
                    ),
                    weights = FX_WEIGHTS,
                    header = true,
                )
                val adverseColor = MaterialTheme.colorScheme.error
                fx.sensibilidad.forEach { row ->
                    val adverse = row.escenarioMxn < 0.0
                    TableRow(
                        cells = listOf(
                            formatSignedPercent(row.escenarioMxn, decimals = 0),
                            formatPercent(row.rendimientoUsdRequerido),
                        ),
                        weights = FX_WEIGHTS,
                        emphasis = adverse,
                        contentColor = if (adverse) adverseColor else null,
                    )
                    // La prosa del engine, completa. Es la que traduce el número
                    // grande a una frase que no se puede malinterpretar.
                    Text(
                        text = row.nota,
                        style = MaterialTheme.typography.bodySmall,
                        color = if (adverse) adverseColor
                        else MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(6.dp))
                }
                Spacer(Modifier.height(6.dp))
                Text(
                    text = stringResource(R.string.why_fx_caption),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(12.dp))
                Text(
                    text = fx.advertencia,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
        }

        Spacer(Modifier.height(24.dp))
    }
}
