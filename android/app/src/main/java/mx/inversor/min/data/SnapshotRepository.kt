package mx.inversor.min.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import mx.inversor.min.AppConfig
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Un día del log walk-forward, tal como aparece en `snapshots/`. */
data class HistoryEntry(
    val date: String,          // "2026-08-10"
    val fileName: String,      // "2026-08-10.json"
    val downloadUrl: String,
)

/**
 * Único punto de red de la app. Tres llamadas, todas GET, todas HTTPS, todas
 * a endpoints públicos. Sin cabeceras de autenticación, sin tokens.
 */
class SnapshotRepository(
    private val cache: LocalCache,
    private val client: OkHttpClient = defaultClient(),
) {

    /** Último snapshot guardado, sin tocar la red. Null si no hay o no parsea. */
    suspend fun cachedSnapshot(): SnapshotDto? = withContext(Dispatchers.IO) {
        val raw = cache.read() ?: return@withContext null
        runCatching { SnapshotParser.parse(raw) }.getOrNull()
    }

    /**
     * Descarga `snapshots/latest.json`. Se parsea ANTES de escribir la caché:
     * nunca se persiste un JSON que la app no pudo leer.
     */
    suspend fun fetchLatest(): SnapshotDto = withContext(Dispatchers.IO) {
        val raw = get(AppConfig.latestUrl)
        val dto = SnapshotParser.parse(raw)
        cache.write(raw)
        dto
    }

    /** Índice del directorio snapshots/ vía GitHub contents API. */
    suspend fun fetchHistoryIndex(): List<HistoryEntry> = withContext(Dispatchers.IO) {
        val raw = get(AppConfig.historyIndexUrl, accept = GITHUB_JSON)
        SnapshotParser.parseContents(raw)
            .asSequence()
            .filter { it.type == "file" && DATED_SNAPSHOT.matches(it.name) }
            .mapNotNull { c ->
                c.downloadUrl?.let {
                    HistoryEntry(date = c.name.removeSuffix(".json"), fileName = c.name, downloadUrl = it)
                }
            }
            .sortedByDescending { it.date }   // ISO ordena lexicográficamente = cronológicamente
            .toList()
    }

    /** Snapshot de un día concreto. No toca la caché: la caché es sólo de "latest". */
    suspend fun fetchDay(entry: HistoryEntry): SnapshotDto = withContext(Dispatchers.IO) {
        SnapshotParser.parse(get(entry.downloadUrl))
    }

    private fun get(url: String, accept: String = "application/json"): String {
        val request = Request.Builder()
            .url(url)
            .header("Accept", accept)
            .header("User-Agent", USER_AGENT)
            .build()
        return client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IOException("HTTP ${response.code} al pedir $url")
            }
            response.body?.string() ?: throw IOException("Respuesta vacía de $url")
        }
    }

    companion object {
        private const val USER_AGENT = "inversor-min-android"
        private const val GITHUB_JSON = "application/vnd.github+json"

        /** Sólo archivos con nombre de fecha ISO. Excluye latest.json a propósito. */
        val DATED_SNAPSHOT = Regex("""^\d{4}-\d{2}-\d{2}\.json$""")

        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(15, TimeUnit.SECONDS)
            .callTimeout(25, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .build()
    }
}
