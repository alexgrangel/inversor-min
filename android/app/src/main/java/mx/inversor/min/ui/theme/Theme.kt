package mx.inversor.min.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf

private val LightColors = lightColorScheme(
    primary = GreenPrimary,
    onPrimary = GreenOnPrimary,
    primaryContainer = GreenContainer,
    onPrimaryContainer = OnGreenContainer,
    secondary = BlueSecondary,
    onSecondary = OnBlueSecondary,
    secondaryContainer = BlueContainer,
    onSecondaryContainer = OnBlueContainer,
    background = SurfaceLight,
    onBackground = OnSurfaceLight,
    surface = SurfaceLight,
    onSurface = OnSurfaceLight,
    surfaceVariant = SurfaceVariantLight,
    onSurfaceVariant = OnSurfaceVariantLight,
    outline = OutlineLight,
    error = RedError,
    onError = OnRedError,
    errorContainer = RedContainerLight,
    onErrorContainer = OnRedContainerLight,
)

private val DarkColors = darkColorScheme(
    primary = GreenPrimaryDark,
    onPrimary = GreenOnPrimaryDark,
    primaryContainer = GreenContainerDark,
    onPrimaryContainer = OnGreenContainerDark,
    secondary = BlueSecondaryDark,
    onSecondary = OnBlueSecondaryDark,
    secondaryContainer = BlueContainerDark,
    onSecondaryContainer = OnBlueContainerDark,
    background = SurfaceDark,
    onBackground = OnSurfaceDark,
    surface = SurfaceDark,
    onSurface = OnSurfaceDark,
    surfaceVariant = SurfaceVariantDark,
    onSurfaceVariant = OnSurfaceVariantDark,
    outline = OutlineDark,
    error = RedErrorDark,
    onError = OnRedErrorDark,
    errorContainer = RedContainerDark,
    onErrorContainer = OnRedContainerDark,
)

/** Lo consulta el chip de acción para elegir su par de colores. */
val LocalIsDarkTheme = staticCompositionLocalOf { false }

@Composable
fun InversorTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    CompositionLocalProvider(LocalIsDarkTheme provides darkTheme) {
        MaterialTheme(
            colorScheme = if (darkTheme) DarkColors else LightColors,
            typography = Typography(),
            content = content,
        )
    }
}
