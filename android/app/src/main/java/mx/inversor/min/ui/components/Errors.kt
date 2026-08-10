package mx.inversor.min.ui.components

import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import mx.inversor.min.LoadError
import mx.inversor.min.R

@Composable
fun loadErrorText(error: LoadError): String = when (error) {
    LoadError.NETWORK -> stringResource(R.string.error_network)
    LoadError.PARSE -> stringResource(R.string.error_parse)
}
