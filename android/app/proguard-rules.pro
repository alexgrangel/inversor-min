# minifyEnabled está en false en ambos build types (app de uso personal por
# sideload). Este archivo existe para que la configuración de release sea válida.
# Si algún día se activa R8, kotlinx.serialization necesita al menos esto:
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers class mx.inversor.min.data.** {
    *** Companion;
}
-keepclasseswithmembers class mx.inversor.min.data.** {
    kotlinx.serialization.KSerializer serializer(...);
}
