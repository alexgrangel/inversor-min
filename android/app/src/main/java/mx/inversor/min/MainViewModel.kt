package mx.inversor.min

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.SerializationException
import mx.inversor.min.data.HistoryEntry
import mx.inversor.min.data.LocalCache
import mx.inversor.min.data.NotificationsLatestDto
import mx.inversor.min.data.SnapshotDto
import mx.inversor.min.data.SnapshotRepository
import mx.inversor.min.util.isSchemaSupported
import java.io.IOException

enum class Source { NONE, CACHE, NETWORK }

enum class LoadError { NETWORK, PARSE }

data class HistoryUi(
    val loading: Boolean = false,
    val error: LoadError? = null,
    val entries: List<HistoryEntry> = emptyList(),
    val loaded: Map<String, SnapshotDto> = emptyMap(),
    val selectedDate: String? = null,
    val loadingDate: String? = null,
    val dayError: LoadError? = null,
)

data class AvisosUi(
    val loading: Boolean = false,
    val error: LoadError? = null,
    val data: NotificationsLatestDto? = null,
    val source: Source = Source.NONE,
)

data class UiState(
    /** true en cuanto se intentó leer la caché: evita el parpadeo inicial. */
    val booted: Boolean = false,
    val refreshing: Boolean = false,
    val snapshot: SnapshotDto? = null,
    val source: Source = Source.NONE,
    val error: LoadError? = null,
    /** Versión del snapshot cuando su mayor no es el soportado. */
    val unsupportedSchemaVersion: String? = null,
    val history: HistoryUi = HistoryUi(),
    val avisos: AvisosUi = AvisosUi(),
)

class MainViewModel(app: Application) : AndroidViewModel(app) {

    private val repository = SnapshotRepository(
        cache = LocalCache(app.filesDir),
        notificationsCache = LocalCache(app.filesDir, LocalCache.NOTIFICATIONS_FILE_NAME),
    )

    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    init {
        viewModelScope.launch {
            // 1. Caché primero. Si ya hubo un día bueno, la app nunca arranca vacía.
            repository.cachedSnapshot()?.let { accept(it, Source.CACHE) }
            _state.update { it.copy(booted = true) }
            // 2. Refresco en segundo plano, con la caché ya en pantalla.
            refresh()
        }
    }

    fun refresh() {
        if (_state.value.refreshing) return
        viewModelScope.launch {
            _state.update { it.copy(refreshing = true, error = null) }
            try {
                accept(repository.fetchLatest(), Source.NETWORK)
            } catch (e: IOException) {
                _state.update { it.copy(error = LoadError.NETWORK) }
            } catch (e: SerializationException) {
                _state.update { it.copy(error = LoadError.PARSE) }
            } finally {
                _state.update { it.copy(refreshing = false) }
            }
        }
        // Los avisos se refrescan junto con el snapshot una vez que la pantalla
        // los pidió por primera vez: son el mismo commit del cron.
        if (_state.value.avisos.data != null) refreshAvisos()
    }

    /** Carga perezosa al entrar a la pestaña Avisos: caché primero, luego red. */
    fun loadAvisosIfNeeded() {
        val avisos = _state.value.avisos
        if (avisos.loading || avisos.data != null) return
        viewModelScope.launch {
            repository.cachedNotifications()?.let { cached ->
                setAvisos { it.copy(data = cached, source = Source.CACHE) }
            }
            refreshAvisosInternal()
        }
    }

    fun refreshAvisos() {
        if (_state.value.avisos.loading) return
        viewModelScope.launch { refreshAvisosInternal() }
    }

    private suspend fun refreshAvisosInternal() {
        setAvisos { it.copy(loading = true, error = null) }
        try {
            val data = repository.fetchNotifications()
            setAvisos { it.copy(data = data, source = Source.NETWORK, loading = false) }
        } catch (e: IOException) {
            setAvisos { it.copy(loading = false, error = LoadError.NETWORK) }
        } catch (e: SerializationException) {
            setAvisos { it.copy(loading = false, error = LoadError.PARSE) }
        }
    }

    private fun setAvisos(transform: (AvisosUi) -> AvisosUi) {
        _state.update { it.copy(avisos = transform(it.avisos)) }
    }

    fun loadHistoryIfNeeded() {
        val history = _state.value.history
        if (history.loading || history.entries.isNotEmpty()) return
        loadHistory()
    }

    fun loadHistory() {
        if (_state.value.history.loading) return
        viewModelScope.launch {
            setHistory { it.copy(loading = true, error = null) }
            try {
                val entries = repository.fetchHistoryIndex()
                setHistory { it.copy(entries = entries, loading = false) }
            } catch (e: IOException) {
                setHistory { it.copy(loading = false, error = LoadError.NETWORK) }
            } catch (e: SerializationException) {
                setHistory { it.copy(loading = false, error = LoadError.PARSE) }
            }
        }
    }

    /** Toca un día del log: lo abre, o lo cierra si ya estaba abierto. */
    fun selectDay(entry: HistoryEntry) {
        val history = _state.value.history
        if (history.selectedDate == entry.date) {
            setHistory { it.copy(selectedDate = null) }
            return
        }
        setHistory { it.copy(selectedDate = entry.date, dayError = null) }
        if (history.loaded.containsKey(entry.date)) return

        viewModelScope.launch {
            setHistory { it.copy(loadingDate = entry.date) }
            try {
                val day = repository.fetchDay(entry)
                setHistory { it.copy(loaded = it.loaded + (entry.date to day), loadingDate = null) }
            } catch (e: IOException) {
                setHistory { it.copy(loadingDate = null, dayError = LoadError.NETWORK) }
            } catch (e: SerializationException) {
                setHistory { it.copy(loadingDate = null, dayError = LoadError.PARSE) }
            }
        }
    }

    /**
     * Regla del contrato engine -> Android: un `schema_version` con mayor
     * distinto no se renderiza a medias. Se descarta el snapshot y la app
     * muestra la pantalla de "actualiza la app".
     */
    private fun accept(snapshot: SnapshotDto, source: Source) {
        if (!isSchemaSupported(snapshot.schemaVersion)) {
            _state.update {
                it.copy(
                    snapshot = null,
                    source = source,
                    unsupportedSchemaVersion = snapshot.schemaVersion,
                )
            }
            return
        }
        _state.update {
            it.copy(snapshot = snapshot, source = source, unsupportedSchemaVersion = null)
        }
    }

    private fun setHistory(transform: (HistoryUi) -> HistoryUi) {
        _state.update { it.copy(history = transform(it.history)) }
    }
}
