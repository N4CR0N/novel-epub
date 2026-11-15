plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

// Sürüm, depodaki VERSION dosyası + derleme hattının verdiği yama numarasından gelir (ör. 1.4.0).
val appVersionName = System.getenv("APP_VERSION_NAME") ?: "dev"
val appVersionCode = (System.getenv("APP_VERSION_CODE") ?: "1").toInt()
val keystorePath: String? = System.getenv("ANDROID_KEYSTORE_PATH")

android {
    namespace = "io.github.n4cr0n.novelepub"
    compileSdk = 35

    defaultConfig {
        applicationId = "io.github.n4cr0n.novelepub"
        minSdk = 24
        targetSdk = 35
        versionCode = appVersionCode
        versionName = appVersionName
        ndk { abiFilters += listOf("arm64-v8a") }
    }

    signingConfigs {
        if (keystorePath != null) {
            create("release") {
                storeFile = file(keystorePath)
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("ANDROID_KEY_ALIAS") ?: "webnovel"
                keyPassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // Kalıcı imza anahtarı yoksa hata ayıklama anahtarıyla imzalanır (sürümler arası güncelleme için kalıcı anahtar gerekir)
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

chaquopy {
    defaultConfig {
        version = "3.12"
        pip {
            // Masaüstündeki curl_cffi, keyring ve pywebview telefonda yok: ağ için net.py sistemin bağlantısını kullanır.
            install("flask")
            install("beautifulsoup4")
            install("pypdf")
            install("certifi")
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.webkit:webkit:1.12.1")
}
