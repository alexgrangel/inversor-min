package mx.inversor.min.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import mx.inversor.min.R
import mx.inversor.min.ui.theme.ActionTone
import mx.inversor.min.ui.theme.LocalIsDarkTheme
import mx.inversor.min.ui.theme.colorsForTone
import mx.inversor.min.ui.theme.toneForAction
import mx.inversor.min.util.Staleness

/** Etiqueta en español de la acción. Una acción nueva del engine se muestra cruda. */
@Composable
fun actionLabel(action: String): String = when (action) {
    "STAY_IN_CETES" -> stringResource(R.string.action_stay_in_cetes)
    "ALLOCATE_TO_CRYPTO" -> stringResource(R.string.action_allocate_to_crypto)
    "REDUCE_CRYPTO" -> stringResource(R.string.action_reduce_crypto)
    "HOLD_NO_ACTION" -> stringResource(R.string.action_hold_no_action)
    "BLOCKED_FEE_BUDGET" -> stringResource(R.string.action_blocked_fee_budget)
    "BLOCKED_STALE_DATA" -> stringResource(R.string.action_blocked_stale_data)
    "BLOCKED_BELOW_MIN_NOTIONAL" -> stringResource(R.string.action_blocked_below_min_notional)
    else -> action
}

@Composable
fun ActionChip(action: String, modifier: Modifier = Modifier, compact: Boolean = false) {
    val colors = colorsForTone(toneForAction(action), LocalIsDarkTheme.current)
    Surface(
        color = colors.container,
        contentColor = colors.content,
        shape = RoundedCornerShape(if (compact) 8.dp else 14.dp),
        modifier = modifier,
    ) {
        Text(
            text = actionLabel(action),
            style = if (compact) MaterialTheme.typography.labelLarge
            else MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.padding(
                horizontal = if (compact) 10.dp else 16.dp,
                vertical = if (compact) 5.dp else 14.dp,
            ),
        )
    }
}

@Composable
fun SectionCard(
    title: String,
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
            contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
        ),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Spacer(Modifier.height(10.dp))
            content()
        }
    }
}

/**
 * Los componentes de tabla toman el color de LocalContentColor en vez de fijar
 * onSurface: así se leen igual dentro de una tarjeta normal que dentro de un
 * bloque destacado (ámbar, azul o rojo).
 */
@Composable
private fun mutedContentColor(): Color = LocalContentColor.current.copy(alpha = 0.75f)

@Composable
fun KeyValueRow(
    label: String,
    value: String,
    emphasis: Boolean = false,
) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 5.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = if (emphasis) FontWeight.Bold else null,
            color = if (emphasis) LocalContentColor.current else mutedContentColor(),
            modifier = Modifier.weight(1.6f),
        )
        Spacer(Modifier.width(8.dp))
        Text(
            text = value,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = if (emphasis) FontWeight.Bold else null,
            textAlign = TextAlign.End,
            color = LocalContentColor.current,
            modifier = Modifier.weight(1f),
        )
    }
}

/**
 * Sin maxLines y sin overflow: los números de esta app nunca se recortan ni se
 * abrevian. Si no cabe, se envuelve. Un "23.4…" sería una mentira barata.
 */
@Composable
fun TableRow(
    cells: List<String>,
    weights: List<Float>,
    header: Boolean = false,
    emphasis: Boolean = false,
    contentColor: Color? = null,
) {
    val muted = mutedContentColor()
    val normal = LocalContentColor.current
    Row(modifier = Modifier.fillMaxWidth().padding(vertical = 5.dp)) {
        cells.forEachIndexed { index, cell ->
            Text(
                text = cell,
                style = if (header) MaterialTheme.typography.labelMedium
                else MaterialTheme.typography.bodyMedium,
                fontWeight = if (emphasis) FontWeight.Bold else null,
                textAlign = if (index == 0) TextAlign.Start else TextAlign.End,
                color = contentColor ?: if (header) muted else normal,
                modifier = Modifier.weight(weights.getOrElse(index) { 1f }),
            )
        }
    }
    if (header) {
        HorizontalDivider(color = muted)
    }
}

@Composable
fun BulletList(items: List<String>, emptyText: String? = null) {
    if (items.isEmpty()) {
        if (emptyText != null) {
            Text(
                text = emptyText,
                style = MaterialTheme.typography.bodyMedium,
                color = mutedContentColor(),
            )
        }
        return
    }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        items.forEach { item ->
            Row(modifier = Modifier.fillMaxWidth()) {
                Text(
                    text = "•",
                    style = MaterialTheme.typography.bodyMedium,
                    color = mutedContentColor(),
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    text = item,
                    style = MaterialTheme.typography.bodyMedium,
                    color = LocalContentColor.current,
                )
            }
        }
    }
}

/** El número grande. Se usa para cetes_anual_mxn en la pantalla Hoy. */
@Composable
fun HeadlineNumber(
    label: String,
    value: String,
    dominant: Boolean = false,
) {
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Text(
            text = value,
            style = if (dominant) MaterialTheme.typography.displayMedium
            else MaterialTheme.typography.displaySmall,
            fontWeight = FontWeight.Bold,
            color = LocalContentColor.current,
        )
        Text(
            text = label,
            style = if (dominant) MaterialTheme.typography.bodyLarge
            else MaterialTheme.typography.bodyMedium,
            color = mutedContentColor(),
        )
    }
}

/**
 * Bloque destacado DENTRO de una tarjeta. Existe para separar visualmente dos
 * números que nunca se deben confundir (tasa anualizada vs tasa del periodo).
 */
@Composable
fun Callout(
    tone: ActionTone,
    modifier: Modifier = Modifier,
    body: @Composable ColumnScope.() -> Unit,
) {
    val colors = colorsForTone(tone, LocalIsDarkTheme.current)
    Surface(
        color = colors.container,
        contentColor = colors.content,
        shape = RoundedCornerShape(10.dp),
        modifier = modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(14.dp), content = body)
    }
}

/**
 * Banner rojo permanente. No es un toast: si el dato está rancio, el usuario
 * lo ve mientras la pantalla esté abierta.
 */
@Composable
fun StaleBanner(staleness: Staleness, maxAgeDays: Long, modifier: Modifier = Modifier) {
    Surface(
        color = MaterialTheme.colorScheme.errorContainer,
        contentColor = MaterialTheme.colorScheme.onErrorContainer,
        modifier = modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(horizontal = 16.dp, vertical = 10.dp)) {
            Text(
                text = stringResource(R.string.banner_stale_title),
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Bold,
            )
            Spacer(Modifier.height(4.dp))
            when {
                staleness.ageUnknown -> Text(
                    text = stringResource(R.string.banner_stale_age_unknown),
                    style = MaterialTheme.typography.bodySmall,
                )

                staleness.tooOld -> Text(
                    text = stringResource(
                        R.string.banner_stale_age,
                        (staleness.ageDays ?: 0L).toInt(),
                        maxAgeDays.toInt(),
                    ),
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            if (staleness.staleSeries.isNotEmpty()) {
                Text(
                    text = stringResource(
                        R.string.banner_stale_series,
                        staleness.staleSeries.joinToString(", "),
                    ),
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            Spacer(Modifier.height(4.dp))
            Text(
                text = stringResource(R.string.banner_stale_footer),
                style = MaterialTheme.typography.bodySmall,
                fontWeight = FontWeight.Bold,
            )
        }
    }
}

/** Banner de datos guardados: "datos del <fecha>". Siempre visible con caché. */
@Composable
fun CacheBanner(
    dateText: String,
    updating: Boolean,
    updateFailed: Boolean,
    modifier: Modifier = Modifier,
) {
    Surface(
        color = MaterialTheme.colorScheme.secondaryContainer,
        contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
        modifier = modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
            Text(
                text = stringResource(R.string.banner_cache_title, dateText),
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Bold,
            )
            val detail = when {
                updating -> stringResource(R.string.banner_cache_updating)
                updateFailed -> stringResource(R.string.banner_cache_offline)
                else -> null
            }
            if (detail != null) {
                Text(text = detail, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}
