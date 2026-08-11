package mx.inversor.min.data

import kotlinx.serialization.SerializationException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * `notifications-latest.json`: el caso real committeado (silencio) y un aviso
 * sintético con la forma EXACTA de notify.Notification.to_dict() del engine.
 */
class NotificationsDtoTest {

    private fun rawReal(): String =
        checkNotNull(javaClass.getResourceAsStream("/notifications-latest.json")) {
            "Falta app/src/test/resources/notifications-latest.json"
        }.bufferedReader(Charsets.UTF_8).use { it.readText() }

    // ── El archivo real: silencio ─────────────────────────────────────────

    @Test
    fun `el archivo real parsea y el silencio es un estado valido`() {
        val n = NotificationsParser.parse(rawReal())
        assertEquals("3.1.0", n.schemaVersion)
        assertTrue(n.generatedAt.startsWith("2026-08-11"))
        assertTrue(n.notifications.isEmpty())
        assertTrue(n.suppressed.isEmpty())
    }

    // ── Aviso completo, forma del engine ──────────────────────────────────

    private val avisoCompleto = """
        {
          "generated_at": "2026-08-10T16:32:26+00:00",
          "schema_version": "3.1.0",
          "notifications": [
            {
              "trigger": "REGIME_FLIPPED",
              "priority": "MEDIUM",
              "title": "Régimen BTC: NEUTRAL → RISK_OFF",
              "body": "Cambió la etiqueta de régimen de al menos un activo del sleeve.",
              "razonamiento": ["BTC: régimen NEUTRAL → RISK_OFF.", "Multiplicador: 0.30 → 0.30."],
              "estrategia": ["No ejecutes por este aviso.", "INVALIDACIÓN: si el hurdle sube de 11.84%, no lo hagas."],
              "changed_from": {"regime": "NEUTRAL"},
              "changed_to": {"regime": "RISK_OFF"},
              "fired_at": "2026-08-10T16:32:26+00:00",
              "dedup_key": "REGIME_FLIPPED:dced817b3283",
              "es_orden_ejecutable": false
            },
            {
              "trigger": "ACTION_CHANGED",
              "priority": "HIGH",
              "title": "Acción: STAY_IN_CETES → ALLOCATE_TO_CRYPTO",
              "body": "La decisión del día cambió.",
              "razonamiento": ["El hurdle bajó."],
              "estrategia": ["Revisa el snapshot antes de mover un peso."],
              "changed_from": {"action": "STAY_IN_CETES"},
              "changed_to": {"action": "ALLOCATE_TO_CRYPTO"},
              "fired_at": "2026-08-10T16:32:26+00:00",
              "dedup_key": "ACTION_CHANGED:abc",
              "es_orden_ejecutable": true
            }
          ],
          "suppressed": [
            {
              "kind": "supresion",
              "trigger": "HURDLE_MOVED",
              "priority": "INFO",
              "title": "Hurdle: 10.84% → 10.79%",
              "dedup_key": "HURDLE_MOVED:xyz",
              "motivo": "cooldown",
              "detalle": "Disparó hace 3 días; cooldown de 21.",
              "at": "2026-08-10T16:32:26+00:00"
            }
          ]
        }
    """.trimIndent()

    @Test
    fun `un aviso con la forma del engine parsea completo`() {
        val n = NotificationsParser.parse(avisoCompleto)
        assertEquals(2, n.notifications.size)

        val regimen = n.notifications[0]
        assertEquals("REGIME_FLIPPED", regimen.trigger)
        assertEquals("MEDIUM", regimen.priority)
        assertTrue(regimen.title.contains("RISK_OFF"))
        assertEquals(2, regimen.razonamiento.size)
        assertEquals(2, regimen.estrategia.size)
        assertFalse(regimen.esOrdenEjecutable)

        // La marca que importa: el aviso que cuesta comisiones (regla 9).
        val orden = n.notifications[1]
        assertTrue(orden.esOrdenEjecutable)
        assertEquals("HIGH", orden.priority)
    }

    @Test
    fun `los suprimidos se leen con motivo y detalle`() {
        val n = NotificationsParser.parse(avisoCompleto)
        assertEquals(1, n.suppressed.size)
        val s = n.suppressed[0]
        assertEquals("HURDLE_MOVED", s.trigger)
        assertEquals("cooldown", s.motivo)
        assertTrue(s.detalle.contains("cooldown de 21"))
        assertTrue(s.at.isNotBlank())
    }

    /** Un registro de supresión con campos faltantes no tira la pantalla. */
    @Test
    fun `supresion con campos faltantes parsea con defaults`() {
        val minimo = """
            {
              "generated_at": "2026-08-10T16:32:26+00:00",
              "schema_version": "3.1.0",
              "notifications": [],
              "suppressed": [{"kind": "supresion", "trigger": "BLOCKER_RAISED"}]
            }
        """.trimIndent()
        val n = NotificationsParser.parse(minimo)
        assertEquals("BLOCKER_RAISED", n.suppressed[0].trigger)
        assertEquals("", n.suppressed[0].motivo)
    }

    /** Quitar un campo del contrato del AVISO sí truena: mejor error que un
     *  aviso a medias en pantalla. */
    @Test
    fun `un aviso sin dedup_key truena`() {
        val roto = avisoCompleto.replace("\"dedup_key\": \"REGIME_FLIPPED:dced817b3283\",", "")
        assertThrows(SerializationException::class.java) { NotificationsParser.parse(roto) }
    }

    @Test
    fun `una respuesta que no es un objeto truena, no crashea`() {
        assertThrows(SerializationException::class.java) { NotificationsParser.parse("[]") }
        assertThrows(SerializationException::class.java) { NotificationsParser.parse("<html>") }
    }
}
