package mx.inversor.min.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import mx.inversor.min.HistoryUi
import mx.inversor.min.LoadError
import mx.inversor.min.R
import mx.inversor.min.data.HistoryEntry
import mx.inversor.min.data.SnapshotDto
import mx.inversor.min.ui.components.ActionChip
import mx.inversor.min.ui.components.KeyValueRow
import mx.inversor.min.ui.components.loadErrorText
import mx.inversor.min.util.formatIsoDate
import mx.inversor.min.util.formatIsoDateTime
import mx.inversor.min.util.formatMxn
import mx.inversor.min.util.formatPercent
import java.time.ZoneId

/**
 * Pantalla 3: el log walk-forward.
 *
 * Esta es la razón de ser del repo: sin el registro fechado, en seis meses no
 * hay forma de distinguir entre que el sistema funcionó y que uno se acuerda
 * de que funcionó. Por eso la pantalla no es un apéndice.
 */
@Composable
fun HistoryScreen(
    history: HistoryUi,
    onLoad: () -> Unit,
    onSelect: (HistoryEntry) -> Unit,
    modifier: Modifier = Modifier,
) {
    LaunchedEffect(Unit) { onLoad() }
    val zone = remember { ZoneId.systemDefault() }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Column {
                Text(
                    text = stringResource(R.string.history_title),
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Spacer(Modifier.height(6.dp))
                Text(
                    text = stringResource(R.string.history_subtitle),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (history.entries.isNotEmpty()) {
                    Spacer(Modifier.height(10.dp))
                    Text(
                        text = stringResource(R.string.history_count, history.entries.size),
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    Text(
                        text = stringResource(R.string.history_tap_hint),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.height(6.dp))
            }
        }

        if (history.loading && history.entries.isEmpty()) {
            item {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.size(12.dp))
                    Text(
                        text = stringResource(R.string.loading),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        val indexError = history.error
        if (indexError != null && history.entries.isEmpty()) {
            item {
                Column {
                    Text(
                        text = stringResource(R.string.history_error),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.error,
                    )
                    Text(
                        text = loadErrorText(indexError),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    TextButton(onClick = onLoad) {
                        Text(stringResource(R.string.retry))
                    }
                }
            }
        }

        if (!history.loading && history.error == null && history.entries.isEmpty()) {
            item {
                Text(
                    text = stringResource(R.string.history_empty),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        items(items = history.entries, key = { it.date }) { entry ->
            HistoryRow(
                entry = entry,
                selected = history.selectedDate == entry.date,
                loading = history.loadingDate == entry.date,
                dayError = if (history.selectedDate == entry.date) history.dayError else null,
                snapshot = history.loaded[entry.date],
                zone = zone,
                onClick = { onSelect(entry) },
            )
        }
    }
}

@Composable
private fun HistoryRow(
    entry: HistoryEntry,
    selected: Boolean,
    loading: Boolean,
    dayError: LoadError?,
    snapshot: SnapshotDto?,
    zone: ZoneId,
    onClick: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        colors = CardDefaults.cardColors(
            containerColor = if (selected) MaterialTheme.colorScheme.surfaceVariant
            else MaterialTheme.colorScheme.surface,
            contentColor = MaterialTheme.colorScheme.onSurface,
        ),
    ) {
        Column(Modifier.padding(14.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    text = formatIsoDate(entry.date),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                )
                when {
                    loading -> CircularProgressIndicator(
                        modifier = Modifier.size(16.dp),
                        strokeWidth = 2.dp,
                    )

                    snapshot != null -> ActionChip(action = snapshot.action, compact = true)
                }
            }

            if (selected && dayError != null) {
                Spacer(Modifier.height(8.dp))
                Text(
                    text = stringResource(R.string.history_day_error),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                )
                Text(
                    text = loadErrorText(dayError),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            if (selected && snapshot != null) {
                Spacer(Modifier.height(10.dp))
                HorizontalDivider(color = MaterialTheme.colorScheme.outline)
                Spacer(Modifier.height(10.dp))
                Text(
                    text = snapshot.headline,
                    style = MaterialTheme.typography.bodyLarge,
                )
                Spacer(Modifier.height(10.dp))
                snapshot.sizing?.let { sizing ->
                    KeyValueRow(
                        label = stringResource(R.string.history_detail_sleeve),
                        value = formatMxn(sizing.weightMxn),
                    )
                }
                // Anualizado a propósito: es lo único comparable entre días si
                // el horizonte cambia. La etiqueta lo dice explícitamente.
                snapshot.hurdle?.let { hurdle ->
                    KeyValueRow(
                        label = stringResource(R.string.history_detail_hurdle),
                        value = formatPercent(hurdle.hurdleTotalAnualizado),
                    )
                }
                snapshot.sizing?.materiality?.let { materiality ->
                    KeyValueRow(
                        label = stringResource(R.string.history_detail_cetes),
                        value = formatMxn(materiality.cetesAnualMxn),
                        emphasis = true,
                    )
                }
                Spacer(Modifier.height(8.dp))
                Text(
                    text = stringResource(
                        R.string.history_detail_generated,
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
        }
    }
}
