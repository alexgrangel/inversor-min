plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

// ─────────────────────────────────────────────────────────────────────────────
// ESTA ES LA ÚNICA LÍNEA QUE HAY QUE EDITAR PARA APUNTAR LA APP A TU REPO.
// Formato: "usuario/repositorio". El repo debe ser público (no hay llaves aquí).
// De aquí salen las dos URLs:
//   https://raw.githubusercontent.com/<repo>/main/snapshots/latest.json
//   https://api.github.com/repos/<repo>/contents/snapshots?ref=main
val snapshotRepo = "OWNER/REPO"
// ─────────────────────────────────────────────────────────────────────────────

android {
    namespace = "mx.inversor.min"
    compileSdk = 35

    defaultConfig {
        applicationId = "mx.inversor.min"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"

        buildConfigField("String", "SNAPSHOT_REPO", "\"$snapshotRepo\"")
        buildConfigField("String", "SNAPSHOT_BRANCH", "\"main\"")
    }

    buildTypes {
        debug {
            // Uso personal por sideload: sin ofuscación, para que el APK sea
            // auditable y no haya que mantener reglas de R8 para kotlinx.serialization.
            isMinifyEnabled = false
        }
        release {
            isMinifyEnabled = false
            isShrinkResources = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)

    val composeBom = platform(libs.androidx.compose.bom)
    implementation(composeBom)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.material.icons.core)
    debugImplementation(libs.androidx.compose.ui.tooling)

    implementation(libs.kotlinx.serialization.json)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.okhttp)

    // testImplementation extiende implementation: los tests JVM ya ven
    // kotlinx.serialization y okhttp sin declararlos otra vez.
    testImplementation(libs.junit)
}
