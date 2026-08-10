package mx.inversor.min.ui.theme

import androidx.compose.ui.graphics.Color

/**
 * Código de color de la acción. Es la primera cosa que se ve al abrir la app,
 * así que el mapeo vive aquí solo y se prueba leyéndolo.
 *
 *   STAY_IN_CETES              azul / neutro
 *   ALLOCATE_TO_CRYPTO         verde
 *   REDUCE_CRYPTO              ámbar
 *   HOLD_NO_ACTION             gris
 *   BLOCKED_*                  rojo
 *   desconocida                gris
 */
enum class ActionTone { BLUE, GREEN, AMBER, GRAY, RED }

fun toneForAction(action: String): ActionTone = when {
    action.startsWith("BLOCKED") -> ActionTone.RED
    action == "ALLOCATE_TO_CRYPTO" -> ActionTone.GREEN
    action == "REDUCE_CRYPTO" -> ActionTone.AMBER
    action == "STAY_IN_CETES" -> ActionTone.BLUE
    action == "HOLD_NO_ACTION" -> ActionTone.GRAY
    else -> ActionTone.GRAY
}

data class TonePair(val container: Color, val content: Color)

fun colorsForTone(tone: ActionTone, dark: Boolean): TonePair = when (tone) {
    ActionTone.BLUE ->
        if (dark) TonePair(BlueContainerDark, OnBlueContainerDark)
        else TonePair(BlueContainer, OnBlueContainer)

    ActionTone.GREEN ->
        if (dark) TonePair(GreenContainerDark, OnGreenContainerDark)
        else TonePair(GreenContainer, OnGreenContainer)

    ActionTone.AMBER ->
        if (dark) TonePair(AmberContainerDark, OnAmberContainerDark)
        else TonePair(AmberContainerLight, OnAmberContainerLight)

    ActionTone.GRAY ->
        if (dark) TonePair(GrayContainerDark, OnGrayContainerDark)
        else TonePair(GrayContainerLight, OnGrayContainerLight)

    ActionTone.RED ->
        if (dark) TonePair(RedContainerDark, OnRedContainerDark)
        else TonePair(RedContainerLight, OnRedContainerLight)
}
