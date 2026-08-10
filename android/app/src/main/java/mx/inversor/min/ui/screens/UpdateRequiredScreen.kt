package mx.inversor.min.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import mx.inversor.min.R
import mx.inversor.min.SUPPORTED_SCHEMA_MAJOR

/**
 * Esquema mayor desconocido. No se renderiza nada del snapshot: media pantalla
 * de números correctos y media de campos vacíos es peor que ninguna pantalla.
 */
@Composable
fun UpdateRequiredScreen(foundVersion: String, modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier.fillMaxSize(),
        color = MaterialTheme.colorScheme.errorContainer,
        contentColor = MaterialTheme.colorScheme.onErrorContainer,
    ) {
        Column(
            modifier = Modifier.fillMaxSize().padding(24.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.Start,
        ) {
            Text(
                text = stringResource(R.string.update_title),
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold,
            )
            Spacer(Modifier.height(16.dp))
            Text(
                text = stringResource(R.string.update_body, foundVersion, SUPPORTED_SCHEMA_MAJOR),
                style = MaterialTheme.typography.bodyLarge,
            )
            Spacer(Modifier.height(16.dp))
            Text(
                text = stringResource(R.string.update_how),
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}
