package mx.inversor.min

import mx.inversor.min.data.SnapshotRepository
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UrlTest {

    @Test
    fun `url del snapshot crudo`() {
        assertEquals(
            "https://raw.githubusercontent.com/alex/inversor-min/main/snapshots/latest.json",
            rawContentUrl("alex/inversor-min", "main", "$SNAPSHOTS_DIR/$LATEST_FILE"),
        )
    }

    @Test
    fun `url del indice de snapshots`() {
        assertEquals(
            "https://api.github.com/repos/alex/inversor-min/contents/snapshots?ref=main",
            contentsApiUrl("alex/inversor-min", "main", SNAPSHOTS_DIR),
        )
    }

    @Test
    fun `solo se listan snapshots con nombre de fecha`() {
        val regex = SnapshotRepository.DATED_SNAPSHOT
        assertTrue(regex.matches("2026-08-10.json"))
        assertTrue(regex.matches("2025-12-31.json"))
        assertFalse(regex.matches("latest.json"))
        assertFalse(regex.matches("latest.md"))
        assertFalse(regex.matches("2026-8-10.json"))
        assertFalse(regex.matches("2026-08-10.md"))
        assertFalse(regex.matches("x2026-08-10.json"))
    }
}
