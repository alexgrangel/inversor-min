package mx.inversor.min.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.JsonObject

/**
 * Espejo de `snapshots/notifications-latest.json` (engine: notify.Notification
 * más los registros de supresión de la auditoría).
 *
 * El caso más frecuente de este archivo es `notifications: []` — y eso NO es
 * un estado de error: el silencio es la salida esperada del motor. La UI lo
 * dice explícitamente en vez de mostrar una lista vacía sin contexto.
 */
@Serializable
data class NotificationsLatestDto(
    @SerialName("generated_at") val generatedAt: String,
    @SerialName("schema_version") val schemaVersion: String,
    val notifications: List<AvisoDto> = emptyList(),
    val suppressed: List<SupresionDto> = emptyList(),
)

@Serializable
data class AvisoDto(
    val trigger: String,
    /** "HIGH" | "MEDIUM" | "INFO" (validado por el engine al construir). */
    val priority: String,
    val title: String,
    val body: String,
    val razonamiento: List<String> = emptyList(),
    val estrategia: List<String> = emptyList(),
    // Diccionarios de forma libre (dependen del trigger): se conservan crudos
    // por si la UI algún día los quiere desglosar; hoy no se renderizan.
    @SerialName("changed_from") val changedFrom: JsonObject? = null,
    @SerialName("changed_to") val changedTo: JsonObject? = null,
    @SerialName("fired_at") val firedAt: String,
    @SerialName("dedup_key") val dedupKey: String,
    /**
     * El campo contra el que se cobra el presupuesto anual derivado (regla 9).
     * La UI lo marca de forma visible: un aviso que carga una orden ejecutable
     * es la salida más cara del sistema y no puede verse igual que los demás.
     */
    @SerialName("es_orden_ejecutable") val esOrdenEjecutable: Boolean = false,
)

/**
 * Lo que NO se avisó y por qué. Mostrarlo (colapsado) es parte del diseño:
 * confiar en el silencio exige poder auditar qué silenció el anti-spam.
 * Todos los campos tienen default: el registro de supresión es auditoría, no
 * contrato — un campo menos no debe tirar la pantalla entera.
 */
@Serializable
data class SupresionDto(
    val trigger: String = "",
    val priority: String = "",
    val title: String = "",
    @SerialName("dedup_key") val dedupKey: String = "",
    val motivo: String = "",
    val detalle: String = "",
    val at: String = "",
)

object NotificationsParser {

    fun parse(raw: String): NotificationsLatestDto {
        val root = SnapshotParser.json.parseToJsonElement(raw) as? JsonObject
            ?: throw SerializationException("La raíz de notifications-latest no es un objeto JSON.")
        return SnapshotParser.json.decodeFromJsonElement(
            NotificationsLatestDto.serializer(), root,
        )
    }
}
