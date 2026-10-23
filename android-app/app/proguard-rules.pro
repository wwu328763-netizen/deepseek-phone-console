# 当前 release 关闭了 R8（与原壳一致）。下面这些规则是为将来打开
# isMinifyEnabled = true 时准备的最小 keep 集，先留着不影响构建。

# 入口组件：Activity / ContentProvider 由清单声明，R8 会保；显式再保一遍更保险
-keep class com.home.phoneconsole.MainActivity { *; }
-keep class com.home.phoneconsole.SetupActivity { *; }
-keep class com.home.phoneconsole.ScannerActivity { *; }
-keep class com.home.phoneconsole.ApkProvider { *; }
-keep class com.home.phoneconsole.QrImageProvider { *; }
-keep class com.home.phoneconsole.UpdateChecker { *; }

# WebView 的 @JavascriptInterface 方法名不能被改
-keepattributes JavascriptInterface
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}

# 扫码库
-keep class com.google.zxing.** { *; }
-dontwarn com.google.zxing.**
