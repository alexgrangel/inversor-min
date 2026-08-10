package mx.inversor.min.data

import java.io.File
import java.io.IOException

/**
 * Caché en almacenamiento interno. Un solo archivo: el último JSON descargado
 * con éxito Y parseado con éxito.
 *
 * Se guarda el texto crudo, no el objeto: si mañana el DTO cambia, el crudo
 * sigue siendo la verdad y se vuelve a parsear con las reglas nuevas.
 */
class LocalCache(dir: File) {

    private val file = File(dir, FILE_NAME)

    /** Texto crudo del último snapshot bueno, o null si no hay caché. */
    fun read(): String? {
        if (!file.exists()) return null
        return try {
            file.readText(Charsets.UTF_8)
        } catch (e: IOException) {
            // Único lugar donde se traga un error a propósito: un fallo de I/O
            // en la caché se degrada a "no hay caché" y la UI queda esperando la
            // red. Nunca produce números; sólo decide si hay algo que pintar.
            null
        }
    }

    fun write(raw: String) {
        try {
            val tmp = File(file.parentFile, "$FILE_NAME.tmp")
            tmp.writeText(raw, Charsets.UTF_8)
            // Escritura atómica: nunca dejar medio archivo si el proceso muere.
            if (!tmp.renameTo(file)) {
                file.writeText(raw, Charsets.UTF_8)
                tmp.delete()
            }
        } catch (e: IOException) {
            // Perder la caché no invalida el dato en pantalla.
        }
    }

    private companion object {
        const val FILE_NAME = "latest_snapshot.json"
    }
}
