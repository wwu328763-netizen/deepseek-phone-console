import org.jetbrains.kotlin.gradle.tasks.KotlinCompile

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// ---------------------------------------------------------------------------
// 签名：固定复用旧壳的 console.keystore（别名 qqmeow）。
// 绝对不能 keytool 重新生成 —— 新包必须能用旧的证书覆盖安装。
// 密码可在命令行用 -P 覆盖，默认值与原 build.ps1 一致。
// ---------------------------------------------------------------------------
val keystoreFile: File = rootProject.file("../android/console.keystore")
val ksAlias: String = (project.findProperty("PHONE_CONSOLE_KEY_ALIAS") as String?) ?: "qqmeow"
val ksStorePass: String = (project.findProperty("PHONE_CONSOLE_STORE_PASSWORD") as String?) ?: "qqmeow123"
val ksKeyPass: String = (project.findProperty("PHONE_CONSOLE_KEY_PASSWORD") as String?) ?: ksStorePass

// 版本号的唯一来源（旧壳在 AndroidManifest.xml 里，这里搬到 build 脚本）
val appVersionCode = 122
val appVersionName = "3.2.2"

android {
    namespace = "com.home.phoneconsole"
    compileSdk = 33
    // 本机只有 33.0.2；固定住避免 AGP 去下别的版本
    buildToolsVersion = "33.0.2"

    defaultConfig {
        applicationId = "com.home.phoneconsole"
        minSdk = 21
        targetSdk = 33
        // 旧壳是 13 / 2.2，这里升到 14 / 2.3 以便覆盖安装后仍能收到更新
        versionCode = appVersionCode
        versionName = appVersionName
    }

    signingConfigs {
        create("release") {
            storeFile = keystoreFile
            storePassword = ksStorePass
            keyAlias = ksAlias
            keyPassword = ksKeyPass
            // minSdk 21 含 Android 6，需要 v1；v2 是 Android 7+ 的主签名
            enableV1Signing = true
            enableV2Signing = true
            // v3/v4 签名：Android 9+ 优先用 v3，安装时校验更完整（Play Protect 也更少猜疑）
            enableV3Signing = true
            enableV4Signing = true
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false        // 与旧壳一致：不混淆，保证已验证逻辑/反射行为不变
            isShrinkResources = false
            signingConfig = signingConfigs.getByName("release")
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
        debug {
            isMinifyEnabled = false
            applicationIdSuffix = ".debug"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }

    buildFeatures {
        buildConfig = true
    }

    // Kotlin 与 Java 混编：Kotlin 放 src/main/kotlin，Java 放 src/main/java
    sourceSets.getByName("main").kotlin.srcDir("src/main/kotlin")

    lint {
        abortOnError = false
        checkReleaseBuilds = false
    }

    packaging {
        resources.excludes += setOf(
            "META-INF/AL2.0",
            "META-INF/LGPL2.1",
            "META-INF/*.kotlin_module",
            "META-INF/DEPENDENCIES",
            "META-INF/LICENSE*",
            "META-INF/NOTICE*"
        )
    }
}

dependencies {
    // 这个壳只用平台 Activity/控件 + 自研 FileProvider，不需要 AndroidX/AppCompat/Material。
    // （之前为"后续 UI 迁移"预置的 appcompat/material/webkit/core-ktx 已移除：
    //   它们让 APK 从 276 KiB 涨到 4.58 MiB，而代码里只用到 core-ktx 的一个 edit{} 扩展，
    //   已改成 Prefs.kt 里的本地 helper。以后真要用 Compose/AndroidX 再加回来。）

    // 扫码解码：与原壳 libs/zxing-core-3.5.3.jar 同版本
    implementation("com.google.zxing:core:3.5.3")
}

// Java 8 目标（与旧脚本 javac -source 8 -target 8 对齐）
tasks.withType<JavaCompile>().configureEach {
    options.encoding = "UTF-8"
    sourceCompatibility = "1.8"
    targetCompatibility = "1.8"
}

tasks.withType<KotlinCompile>().configureEach {
    kotlinOptions {
        jvmTarget = "1.8"
        freeCompilerArgs = freeCompilerArgs + listOf("-Xjvm-default=all")
    }
}

// 可选任务：把 release APK 复制到旧壳的发布目录，命名与旧脚本一致。
// 用法： .\gradlew.bat assembleRelease publishApk
tasks.register<Copy>("publishApk") {
    dependsOn("assembleRelease")
    from(layout.buildDirectory.file("outputs/apk/release/app-release.apk"))
    into(rootProject.file("../android/build"))
    rename { "PhoneConsole-v$appVersionName.apk" }
}
