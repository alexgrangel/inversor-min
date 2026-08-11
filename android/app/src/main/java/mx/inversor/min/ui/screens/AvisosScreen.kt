package mx.inversor.min.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import mx.inversor.min.AvisosUi
import mx.inversor.min.R
import mx.inversor.min.data.AvisoDto
import mx.inversor.min.data.SupresionDto
import mx.inversor.min.ui.components.BulletList
import mx.inversor.min.ui.components.loadErrorText
import java.time.ZoneId
import mx.inversor.min.util.formatIsoDateTime

/**
 * Pantalla 4: los avisos de la última corrida, tal como los emitió (o
 * silenció) el motor.
 *
 * Dos decisiones de esta pantalla no son decoración:
 *  - Un aviso con `es_orden_ejecutable` lleva una marca imposible de no ver:
 *    es la salida más cara del sistema (cuenta contra el presupuesto anual
 *    derivado de comisiones, regla 9) y no puede verse igual que un aviso
 *    informativo.
 *  - Los SUPRIMIDOS se muestran, colapsados. Ver qué NO se te avisó y por qué
 *    es parte de poder confiar en el silencio.
 */
@Composable
fun AvisosScreen(
    avisos: AvisosUi,
    onLoad: () -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    LaunchedEffect(Unit) { onLoad() }

    val data = avisos.data
    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        if (avisos.loading) {
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }

        val error = avisos.error
        if (error != null && !avisos.loading) {
            Surface(
                color = MaterialTheme.colorScheme.errorContainer,
                contentColor = MaterialTheme.colorScheme.onErrorContainer,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(Modifier.padding(12.dp)) {
                    Text(
                        text = loadErrorText(error),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    TextButton(onClick = onRetry) { Text(stringResource(R.string.retry)) }
                }
            }
        }

        if (data != null) {
            Text(
                text = stringResource(
                    R.string.avisos_generated,
                    formatIsoDateTime(data.generatedAt, ZoneId.systemDefault()),
                ),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            if (data.notifications.isEmpty()) {
                SilencioCard()
            } else {
                val ordenes = data.notifications.count { it.esOrdenEjecutable }
                Text(
                    text = if (ordenes == 0) {
                        stringResource(R.string.avisos_orders_none, data.notifications.size)
                    } else {
                        stringResource(R.string.avisos_orders_some, data.notifications.size, ordenes)
                    },
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Bold,
                )
                data.notifications.forEach { AvisoCard(it) }
            }

            SuprimidosCard(data.suppressed)
        } else if (!avisos.loading && error == null) {
            Text(
                text = stringResource(R.string.loading),
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        Spacer(Modifier.height(24.dp))
    }
}

/** El caso más frecuente y más valioso: silencio, dicho con todas sus letras. */
@Composable
private fun SilencioCard() {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text(
                text = stringResource(R.string.avisos_none_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
            )
            Spacer(Modifier.height(6.dp))
            Text(
                text = stringResource(R.string.avisos_none_body),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun AvisoCard(aviso: AvisoDto) {
    val esOrden = aviso.esOrdenEjecutable
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = if (esOrden) {
            CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.tertiaryContainer,
                contentColor = MaterialTheme.colorScheme.onTertiaryContainer,
            )
        } else {
            CardDefaults.cardColors()
        },
    ) {
        Column(Modifier.padding(16.dp)) {
            if (esOrden) {
                Surface(
                    color = MaterialTheme.colorScheme.error,
                    contentColor = MaterialTheme.colorScheme.onError,
                ) {
                    Text(
                        text = stringResource(R.string.avisos_executable_badge),
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = FontWeight.Black,
                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
                    )
                }
                Spacer(Modifier.height(8.dp))
            }
            Text(
                text = "[${prioridadEs(aviso.priority)}] ${aviso.title}",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
            )
            Spacer(Modifier.height(6.dp))
            Text(text = aviso.body, style = MaterialTheme.typography.bodyMedium)

            Seccion(stringResource(R.string.avisos_why))
            BulletList(items = aviso.razonamiento, emptyText = "")

            Seccion(stringResource(R.string.avisos_what))
            BulletList(items = aviso.estrategia, emptyText = "")

            Spacer(Modifier.height(8.dp))
            Text(
                text = "${aviso.trigger} · ${formatIsoDateTime(aviso.firedAt, ZoneId.systemDefault())}",
                style = MaterialTheme.typography.bodySmall,
                color = LocalContentColorVariant(),
            )
        }
    }
}

@Composable
private fun SuprimidosCard(suprimidos: List<SupresionDto>) {
    var expandido by rememberSaveable { mutableStateOf(false) }
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            Modifier
                .fillMaxWidth()
                .clickable { expandido = !expandido }
                .padding(16.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = stringResource(R.string.avisos_suppressed_title, suprimidos.size),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.weight(1f),
                )
                Icon(
                    imageVector = if (expandido) {
                        Icons.Filled.KeyboardArrowUp
                    } else {
                        Icons.Filled.KeyboardArrowDown
                    },
                    contentDescription = null,
                )
            }
            Text(
                text = stringResource(R.string.avisos_suppressed_caption),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (expandido) {
                Spacer(Modifier.height(10.dp))
                if (suprimidos.isEmpty()) {
                    Text(
                        text = stringResource(R.string.avisos_suppressed_empty),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                suprimidos.forEach { s ->
                    Column(Modifier.padding(vertical = 6.dp)) {
                        Text(
                            text = listOf(s.trigger, s.title)
                                .filter { it.isNotBlank() }
                                .joinToString(" — "),
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = FontWeight.Bold,
                        )
                        val motivo = listOf(s.motivo, s.detalle)
                            .filter { it.isNotBlank() }
                            .joinToString(": ")
                        if (motivo.isNotBlank()) {
                            Text(text = motivo, style = MaterialTheme.typography.bodySmall)
                        }
                        if (s.at.isNotBlank()) {
                            Text(
                                text = formatIsoDateTime(s.at, ZoneId.systemDefault()),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun Seccion(titulo: String) {
    Spacer(Modifier.height(10.dp))
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(
            text = titulo,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Bold,
        )
        Spacer(Modifier.width(4.dp))
    }
    Spacer(Modifier.height(4.dp))
}

@Composable
private fun LocalContentColorVariant() = MaterialTheme.colorScheme.onSurfaceVariant

private fun prioridadEs(priority: String): String = when (priority) {
    "HIGH" -> "ALTA"
    "MEDIUM" -> "MEDIA"
    "INFO" -> "INFO"
    else -> priority
}
