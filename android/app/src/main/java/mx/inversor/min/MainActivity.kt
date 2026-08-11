package mx.inversor.min

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.collectAsState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import mx.inversor.min.data.HistoryEntry
import mx.inversor.min.data.SnapshotDto
import mx.inversor.min.ui.components.CacheBanner
import mx.inversor.min.ui.components.StaleBanner
import mx.inversor.min.ui.components.loadErrorText
import mx.inversor.min.ui.screens.AvisosScreen
import mx.inversor.min.ui.screens.HistoryScreen
import mx.inversor.min.ui.screens.TodayScreen
import mx.inversor.min.ui.screens.UpdateRequiredScreen
import mx.inversor.min.ui.screens.WhyScreen
import mx.inversor.min.ui.theme.InversorTheme
import mx.inversor.min.util.evaluateStaleness
import mx.inversor.min.util.formatIsoInstantAsDate
import java.time.Instant
import java.time.ZoneId

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            InversorTheme {
                val viewModel: MainViewModel = viewModel()
                val state by viewModel.state.collectAsState()
                AppRoot(
                    state = state,
                    onRefresh = viewModel::refresh,
                    onLoadHistory = viewModel::loadHistoryIfNeeded,
                    onSelectDay = viewModel::selectDay,
                    onLoadAvisos = viewModel::loadAvisosIfNeeded,
                    onRetryAvisos = viewModel::refreshAvisos,
                )
            }
        }
    }
}

private const val TAB_TODAY = 0
private const val TAB_WHY = 1
private const val TAB_HISTORY = 2
private const val TAB_AVISOS = 3

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppRoot(
    state: UiState,
    onRefresh: () -> Unit,
    onLoadHistory: () -> Unit,
    onSelectDay: (HistoryEntry) -> Unit,
    onLoadAvisos: () -> Unit,
    onRetryAvisos: () -> Unit,
) {
    var tab by rememberSaveable { mutableStateOf(TAB_TODAY) }
    val unsupported = state.unsupportedSchemaVersion

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.app_name)) },
                actions = {
                    IconButton(onClick = onRefresh, enabled = !state.refreshing) {
                        Icon(
                            imageVector = Icons.Filled.Refresh,
                            contentDescription = stringResource(R.string.cd_refresh),
                        )
                    }
                },
            )
        },
        bottomBar = {
            if (unsupported == null) {
                NavigationBar {
                    NavigationBarItem(
                        selected = tab == TAB_TODAY,
                        onClick = { tab = TAB_TODAY },
                        icon = { Icon(Icons.Filled.Home, contentDescription = null) },
                        label = { Text(stringResource(R.string.tab_today)) },
                    )
                    NavigationBarItem(
                        selected = tab == TAB_WHY,
                        onClick = { tab = TAB_WHY },
                        icon = { Icon(Icons.Filled.Info, contentDescription = null) },
                        label = { Text(stringResource(R.string.tab_why)) },
                    )
                    NavigationBarItem(
                        selected = tab == TAB_HISTORY,
                        onClick = { tab = TAB_HISTORY },
                        icon = { Icon(Icons.Filled.DateRange, contentDescription = null) },
                        label = { Text(stringResource(R.string.tab_history)) },
                    )
                    NavigationBarItem(
                        selected = tab == TAB_AVISOS,
                        onClick = { tab = TAB_AVISOS },
                        icon = { Icon(Icons.Filled.Notifications, contentDescription = null) },
                        label = { Text(stringResource(R.string.tab_avisos)) },
                    )
                }
            }
        },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .padding(innerPadding)
                .fillMaxSize(),
        ) {
            if (unsupported != null) {
                UpdateRequiredScreen(foundVersion = unsupported)
            } else {
                if (state.refreshing) {
                    LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                }

                val snapshot = state.snapshot
                if (snapshot != null) {
                    Banners(state = state, snapshot = snapshot)
                }

                when {
                    tab == TAB_AVISOS -> AvisosScreen(
                        avisos = state.avisos,
                        onLoad = onLoadAvisos,
                        onRetry = onRetryAvisos,
                    )
                    snapshot == null -> EmptyState(state = state, onRefresh = onRefresh)
                    tab == TAB_TODAY -> TodayScreen(snapshot = snapshot)
                    tab == TAB_WHY -> WhyScreen(snapshot = snapshot)
                    else -> HistoryScreen(
                        history = state.history,
                        onLoad = onLoadHistory,
                        onSelect = onSelectDay,
                    )
                }
            }
        }
    }
}

/**
 * La frescura es estado de primera clase: los dos banners viven arriba de las
 * tres pantallas y no se pueden descartar.
 */
@Composable
private fun Banners(state: UiState, snapshot: SnapshotDto) {
    val zone = remember { ZoneId.systemDefault() }
    val staleness = remember(snapshot) { evaluateStaleness(snapshot, Instant.now()) }

    if (staleness.isStale) {
        StaleBanner(staleness = staleness, maxAgeDays = MAX_SNAPSHOT_AGE_DAYS)
    }

    if (state.source == Source.CACHE) {
        CacheBanner(
            dateText = formatIsoInstantAsDate(snapshot.generatedAt, zone),
            updating = state.refreshing,
            updateFailed = state.error != null && !state.refreshing,
        )
    } else {
        val error = state.error
        if (error != null && !state.refreshing) {
            Surface(
                color = MaterialTheme.colorScheme.errorContainer,
                contentColor = MaterialTheme.colorScheme.onErrorContainer,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    text = loadErrorText(error),
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                )
            }
        }
    }
}

@Composable
private fun EmptyState(state: UiState, onRefresh: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        val error = state.error
        when {
            !state.booted || state.refreshing -> Text(
                text = stringResource(R.string.loading),
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            error != null -> {
                Text(
                    text = loadErrorText(error),
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.error,
                )
                Spacer(Modifier.height(12.dp))
                TextButton(onClick = onRefresh) { Text(stringResource(R.string.retry)) }
            }

            else -> {
                Text(
                    text = stringResource(R.string.empty_no_data),
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(12.dp))
                TextButton(onClick = onRefresh) { Text(stringResource(R.string.retry)) }
            }
        }
    }
}
