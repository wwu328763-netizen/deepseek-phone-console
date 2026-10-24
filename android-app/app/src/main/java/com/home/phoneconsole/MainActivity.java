package com.home.phoneconsole;

import android.app.Activity;
import android.content.Intent;
import android.content.res.Configuration;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;

/**
 * 界面 2：主界面（WebView）。
 * 全屏加载控制台页面；支持文件上传（📎）、Fullscreen API（⛶）、返回键返回上一层、
 * 友好的错误页、长按/菜单里的「重新设置地址 / 检查更新 / 刷新」。
 */
public class MainActivity extends Activity {

    private static final String TAG = "MainActivity";
    private static final int REQ_FILE_CHOOSER = 1001;

    private WebView web;
    private ProgressBar bar;
    private TextView titleView;
    /** 顶栏容器与"⋮"菜单：切主题时要一起改颜色 */
    private LinearLayout topBar;
    private TextView menuBtnView;
    /** 页面最近一次报告的主题（退出全屏时恢复状态栏颜色用） */
    private boolean lastThemeDark = false;
    private FrameLayout content;

    private View errorView;
    private ViewGroup webParent;
    private ViewGroup.LayoutParams webLp;

    private ValueCallback<Uri[]> filePathCallback;
    /** 进入聊天前的原生加载遮罩（避免隧道慢时长时间空白） */
    private View loadingView;
    private View customView;
    private WebChromeClient.CustomViewCallback customViewCallback;
    private int originalUiFlags;

    private static boolean sCrashLoggerInstalled = false;
    private long lastBackTime = 0L;
    private boolean loadFailed = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // 顶部不要出现黑条：Activity 主题是 Theme.Material.Light.NoActionBar，
        // 状态栏默认近黑，和浅色页面接在一起就是一条黑栏
        installCrashLogger(this);

        applyLightSystemBars();

        if (!Prefs.isConfigured(this)) {
            startActivity(new Intent(this, SetupActivity.class));
            finish();
            return;
        }

        content = new FrameLayout(this);
        content.setBackgroundColor(Color.WHITE);

        // ---- 原生顶栏已移除 ----
        // 网页自己有顶栏（☰ / 标题 / 设置 / 新建），原生再叠一条既重复又占掉约 44px。
        // 原来顶栏里的「刷新 / 重新设置地址 / 检查更新」已搬进网页「设置 → App」分区；
        // 长按网页仍可叫出旧的原生菜单（出问题时的后门）。
        // 这里只保证 content 的底部留白（导航栏/键盘），顶部由 applySysInsets 补状态栏高度。

        // ---- WebView ----
        web = new WebView(this);
        FrameLayout.LayoutParams wlp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
        wlp.topMargin = 0;
        content.addView(web, wlp);

        // ---- 顶部细进度条 ----
        bar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        bar.setMax(100);
        FrameLayout.LayoutParams blp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, (int) (getResources().getDisplayMetrics().density * 2));
        blp.topMargin = 0;
        content.addView(bar, blp);

        loadingView = buildLoadingView();
        content.addView(loadingView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        setContentView(content);

        // 不再铺到状态栏/导航栏下面：让系统直接把内容区放在安全区内。
        // 之前用 edge-to-edge + 手补 insets，结果 WebView 上下各空出一条（真机反馈“上下两块空白”）。
        try {
            if (Build.VERSION.SDK_INT >= 30) getWindow().setDecorFitsSystemWindows(true);
            getWindow().getDecorView().setSystemUiVisibility(0);
        } catch (Throwable ignored) {
        }

        // 长按不再拦成原生菜单：要让系统文字选择（复制/全选/分享）工作。
        // 旧菜单改成「长按标题」再叫出来（见下方 appIcon 长按），不影响正文复制。
        web.setLongClickable(true);
        web.setHapticFeedbackEnabled(false);

        setupWebView();
        loadConsole();

        // 过渡：从连接页进来时整体淡入，WebView 内容 0.22s 渐显（避免白屏硬切）
        try {
            web.setAlpha(0f);
            web.animate().alpha(1f).setDuration(240).start();
        } catch (Throwable ignored) {
        }
    }

    // ------------------------------------------------------------------
    // WebView 配置
    // ------------------------------------------------------------------

    /**
     * 按系统栏 insets 给原生顶栏和 WebView 补边距（只在 edge-to-edge 模式下用）。
     * 全屏时 statusBars/navigationBars 被隐藏 → 这里的 top/bottom 变成 0，
     * 内容自然铺满整屏，全屏黑边因此消失。
     */
    private int dp(int v) {
        return Math.round(getResources().getDisplayMetrics().density * v);
    }

    /** 保留占位：现在改为系统安全区布局，不再手动补 insets（避免上下空白） */
    @SuppressWarnings("unused")
    private void applySysInsets(int top, int bottom) {
        if (true) return;
        try {
            // 原生顶栏已去掉：WebView 直接从状态栏下沿开始，只补状态栏高度
            int barH = top;
            if (topBar != null) {
                ViewGroup.LayoutParams lp = topBar.getLayoutParams();
                if (lp != null) {
                    lp.height = dp(44) + top;
                    topBar.setLayoutParams(lp);
                }
                topBar.setPadding(dp(10), dp(10) + top, dp(10), dp(10));
            }
            if (web != null && web.getLayoutParams() instanceof FrameLayout.LayoutParams) {
                FrameLayout.LayoutParams lp = (FrameLayout.LayoutParams) web.getLayoutParams();
                lp.topMargin = barH;
                web.setLayoutParams(lp);
            }
            if (bar != null && bar.getLayoutParams() instanceof FrameLayout.LayoutParams) {
                FrameLayout.LayoutParams lp = (FrameLayout.LayoutParams) bar.getLayoutParams();
                lp.topMargin = barH;
                bar.setLayoutParams(lp);
            }
            if (content != null) content.setPadding(0, 0, 0, bottom);
        } catch (Throwable t) {
            Log.w(TAG, "applySysInsets", t);
        }
    }

    /** 浅色系统栏：状态栏/导航栏与页面同色 + 深色图标，避免顶部一条黑栏。 */
    private void applyLightSystemBars() {
        try {
            int flags = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;                  // API 23+
            if (Build.VERSION.SDK_INT >= 26) {
                flags |= View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;             // API 26+
            }
            getWindow().getDecorView().setSystemUiVisibility(flags);
            if (Build.VERSION.SDK_INT >= 21) {
                getWindow().setStatusBarColor(Color.parseColor("#E6E6E6"));
                getWindow().setNavigationBarColor(Color.parseColor("#E6E6E6"));
            }
        } catch (Throwable t) {
            Log.w(TAG, "applyLightSystemBars", t);
        }
    }

    private void setupWebView() {
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(true);
        s.setSupportZoom(true);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);
        s.setAllowFileAccess(true);
        s.setAllowContentAccess(true);
        s.setJavaScriptCanOpenWindowsAutomatically(true);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        // 局域网是 http，页面里可能混用，全部放行
        try {
            s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        } catch (Throwable t) {
            Log.w(TAG, "setMixedContentMode not supported", t);
        }
        String ua = s.getUserAgentString();
        if (ua != null && ua.indexOf("PhoneConsoleApp") < 0) {
            s.setUserAgentString(ua + " PhoneConsoleApp/1.0");
        }
        try {
            CookieManager.getInstance().setAcceptCookie(true);
        } catch (Throwable ignored) {
        }
        web.addJavascriptInterface(new PageBridge(), "PhoneConsole");
        web.setWebViewClient(new ConsoleClient());
        web.setWebChromeClient(new ConsoleChromeClient());
        // 页面里如果有下载链接，至少别静默失败
        web.setDownloadListener(new android.webkit.DownloadListener() {
            @Override
            public void onDownloadStart(String url, String userAgent, String contentDisposition,
                                        String mimetype, long contentLength) {
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                } catch (Throwable t) {
                    toast("无法打开下载链接：" + url);
                }
            }
        });
    }

    /** 启动期崩溃落盘到 files/last-crash.txt，方便用户把原因发回来 */
    private static void installCrashLogger(final android.content.Context appCtx) {
        try {
            if (sCrashLoggerInstalled) return;
            sCrashLoggerInstalled = true;
            final Thread.UncaughtExceptionHandler def = Thread.getDefaultUncaughtExceptionHandler();
            Thread.setDefaultUncaughtExceptionHandler(new Thread.UncaughtExceptionHandler() {
                @Override
                public void uncaughtException(Thread t, Throwable e) {
                    try {
                        java.io.File f = new java.io.File(appCtx.getFilesDir(), "last-crash.txt");
                        java.io.FileOutputStream fo = new java.io.FileOutputStream(f);
                        fo.write(("time=" + new java.util.Date() + "\n" + Log.getStackTraceString(e)).getBytes("UTF-8"));
                        fo.close();
                    } catch (Throwable ignored) {
                    }
                    if (def != null) def.uncaughtException(t, e);
                }
            });
        } catch (Throwable ignored) {
        }
    }

    private String consoleUrl() {
        // 「启动时显示登录页」打开时不把 PIN 放进 URL，网页会先要 PIN
        String pin = Prefs.getRequireLogin(this) ? "" : Prefs.getPin(this);
        return SetupActivity.buildUrl(Prefs.getHost(this), pin);
    }

    private void loadConsole() {
        errorView = null;
        loadFailed = false;
        if (loadingView != null) loadingView.setVisibility(View.VISIBLE);
        String url = consoleUrl();
        // 原生顶栏已移除：titleView 永远是 null，之前这里直接 NPE → 启动瞬间闪退
        if (titleView != null) titleView.setText(Prefs.getHost(this));
        web.setVisibility(View.VISIBLE);
        web.loadUrl(url);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (web != null) {
            web.setVisibility(View.VISIBLE);
            loadConsole();
        }
    }

    // ------------------------------------------------------------------
    // WebViewClient：错误处理
    // ------------------------------------------------------------------

    private class ConsoleClient extends WebViewClient {

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, String url) {
            return handleUrl(url);
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            if (request == null || request.getUrl() == null) return false;
            return handleUrl(request.getUrl().toString());
        }

        /** 站外 http(s) 交给系统浏览器；站内继续在 WebView 里跑 */
        private boolean handleUrl(String url) {
            if (url == null) return false;
            try {
                Uri uri = Uri.parse(url);
                String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase();
                if (scheme.equals("http") || scheme.equals("https")) {
                    String host = uri.getHost() == null ? "" : uri.getHost();
                    String configured = Prefs.getHost(MainActivity.this);
                    String configuredHost = configured;
                    int sc = configuredHost.indexOf("://");   // 先去掉 scheme（隧道地址是 https://）
                    if (sc >= 0) configuredHost = configuredHost.substring(sc + 3);
                    int sl = configuredHost.indexOf('/');
                    if (sl >= 0) configuredHost = configuredHost.substring(0, sl);
                    int c = configuredHost.lastIndexOf(':');
                    if (c > 0) configuredHost = configuredHost.substring(0, c);
                    if (!host.equalsIgnoreCase(configuredHost)) {
                        startActivity(new Intent(Intent.ACTION_VIEW, uri));
                        return true;
                    }
                }
            } catch (Throwable t) {
                Log.w(TAG, "handleUrl", t);
            }
            return false;
        }

        @Override
        public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
            bar.setVisibility(View.VISIBLE);
            bar.setProgress(5);
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            bar.setVisibility(View.GONE);
            bar.setProgress(0);
            if (loadingView != null) loadingView.setVisibility(View.GONE);
            fadeInWeb();
            // Cloudflare 隧道失效时返回的是 HTTP 200 的自定义错误页，WebView 不会走 onReceivedError，
            // 这里读一下页面文字，命中 1033 就换成原生错误页（带"重试 / 换地址 / 回登录页"）。
            if (url != null && !url.startsWith("data:text/html")) {
                view.evaluateJavascript(
                        "(document.body?document.body.innerText:'').slice(0,300)",
                        new android.webkit.ValueCallback<String>() {
                            @Override
                            public void onReceiveValue(String text) {
                                String t = text == null ? "" : text.replace("\\n", " ");
                                if (t.contains("Error 1033") || t.contains("Cloudflare Tunnel error")
                                        || t.contains("unable to resolve it")) {
                                    showErrorPage("隧道地址已失效（Cloudflare Error 1033）：电脑重启后地址会变，请重新扫码");
                                }
                            }
                        });
            }
        }

        // API < 23 的主框架错误回调
        @Override
        public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
            if (failingUrl == null || failingUrl.equals(view.getUrl())) {
                showErrorPage(description == null ? ("错误码 " + errorCode) : description);
            }
        }

        // API >= 23：只对主框架报错出错误页，子资源失败忽略（否则图裂一个就整页替换）
        @Override
        public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (request == null || !request.isForMainFrame()) return;
            CharSequence desc = null;
            try {
                if (error != null) desc = error.getDescription();
            } catch (Throwable ignored) {
            }
            showErrorPage(desc == null ? "网络请求失败" : desc.toString());
        }
    }

    /** 原生加载遮罩：图标 + 旋转圈 + 文案（隧道慢/首屏白屏时给反馈） */
    private View buildLoadingView() {
        android.widget.LinearLayout box = new android.widget.LinearLayout(this);
        box.setOrientation(android.widget.LinearLayout.VERTICAL);
        box.setGravity(android.view.Gravity.CENTER);
        box.setBackgroundColor(android.graphics.Color.WHITE);

        android.widget.ImageView icon = new android.widget.ImageView(this);
        icon.setImageResource(R.mipmap.ic_launcher);
        android.widget.LinearLayout.LayoutParams ilp = new android.widget.LinearLayout.LayoutParams(
                (int) (getResources().getDisplayMetrics().density * 64),
                (int) (getResources().getDisplayMetrics().density * 64));
        ilp.bottomMargin = (int) (getResources().getDisplayMetrics().density * 18);
        box.addView(icon, ilp);

        ProgressBar spinner = new ProgressBar(this);
        box.addView(spinner, new android.widget.LinearLayout.LayoutParams(
                android.widget.LinearLayout.LayoutParams.WRAP_CONTENT,
                android.widget.LinearLayout.LayoutParams.WRAP_CONTENT));

        android.widget.TextView tv = new android.widget.TextView(this);
        tv.setText("正在连接电脑…");
        tv.setTextSize(13f);
        tv.setTextColor(android.graphics.Color.parseColor("#6B7280"));
        android.widget.LinearLayout.LayoutParams tlp = new android.widget.LinearLayout.LayoutParams(
                android.widget.LinearLayout.LayoutParams.WRAP_CONTENT,
                android.widget.LinearLayout.LayoutParams.WRAP_CONTENT);
        tlp.topMargin = (int) (getResources().getDisplayMetrics().density * 12);
        box.addView(tv, tlp);
        return box;
    }

    /** 内容淡入（页面加载完成后调用，避免硬切） */
    private void fadeInWeb() {
        try {
            if (web != null && web.getAlpha() < 1f) {
                web.animate().alpha(1f).setDuration(220).start();
            }
        } catch (Throwable ignored) {
        }
    }

    /** 出错时给出可操作的错误页，而不是白屏 */
    private void showErrorPage(String detail) {
        loadFailed = true;
        bar.setVisibility(View.GONE);
        web.setVisibility(View.GONE);

        String host = Prefs.getHost(this);
        String html = "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
                + "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                + "<style>body{font-family:-apple-system,'PingFang SC',sans-serif;margin:0;padding:28px 20px;"
                + "background:#F2F2F7;color:#111}h1{font-size:19px;margin:0 0 10px}p{font-size:14px;"
                + "color:#3C3C43;line-height:1.7;margin:6px 0}code{background:#E5E5EA;padding:2px 6px;border-radius:4px}"
                + "button{display:block;width:100%;margin-top:12px;padding:13px;font-size:15px;border:0;"
                + "border-radius:10px;background:#07C160;color:#fff}button.sec{background:#fff;color:#07C160;"
                + "border:1px solid #07C160}</style></head><body>"
                + "<h1>连不上电脑上的控制台</h1>"
                + "<p>当前地址：<code>" + escapeHtml(host) + "</code></p>"
                + "<p>原因：" + escapeHtml(detail) + "</p>"
                + "<p>请检查：<br>1. 电脑上的「手机远程控制台」是否正在运行<br>"
                + "2. 手机和电脑是否连在同一个 Wi-Fi<br>"
                + "3. 地址/端口是否正确（默认 8787），电脑防火墙是否放行</p>"
                + "<button onclick=\"PhoneConsole.reload()\">重试</button>"
                + "<button class=\"sec\" onclick=\"PhoneConsole.toSettings()\">重新设置地址</button>"
                + "<button class=\"sec\" onclick=\"PhoneConsole.logout()\">返回登录界面</button>"
                + "</body></html>";

        if (errorView == null) {
            errorView = new View(this); // 仅作为「已进入错误页」的标记
        }
        if (loadingView != null) loadingView.setVisibility(View.GONE);
        web.loadDataWithBaseURL(null, html, "text/html", "UTF-8", null);
        web.setVisibility(View.VISIBLE);
    }

    private static String escapeHtml(String s) {
        if (s == null) return "";
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace("\"", "&quot;");
    }

    /** 错误页按钮回调 */
    private class PageBridge {
        /** 网页登录页可以用它自动填 PIN（扫码/保存过就不用手输） */
        @JavascriptInterface
        public String pin() {
            try {
                return Prefs.getPin(MainActivity.this);
            } catch (Throwable t) {
                return "";
            }
        }

        /** 保留原生菜单入口（长按标题可用） */
        @JavascriptInterface
        public void showMenuBridge() {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    showMenu();
                }
            });
        }
        @JavascriptInterface
        public void toSettings() {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    startActivity(new Intent(MainActivity.this, SetupActivity.class));
                }
            });
        }

        /** 返回登录页：清掉保存的 PIN，并强制下次加载先显示PIN页 */
        @JavascriptInterface
        public void logout() {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    try {
                        Prefs.save(MainActivity.this, Prefs.getHost(MainActivity.this), "");
                        Prefs.setRequireLogin(MainActivity.this, true);
                    } catch (Throwable ignored) {
                    }
                    loadConsole();
                }
            });
        }

        @JavascriptInterface
        public void reload() {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    loadConsole();
                }
            });
        }

        /** 让页面能显示"壳的版本号"（诊断里用来看清装的是哪一版 App） */
        @JavascriptInterface
        public String appVersion() {
            try {
                android.content.pm.PackageInfo pi = getPackageManager()
                        .getPackageInfo(getPackageName(), 0);
                return pi.versionName + " (" + pi.versionCode + ")";
            } catch (Throwable t) {
                return "unknown";
            }
        }

        /** 检查更新（网页设置里的「检查更新」调用；原生菜单已移除） */
        @JavascriptInterface
        public void checkUpdate() {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    new UpdateChecker(MainActivity.this, Prefs.getHost(MainActivity.this)).check(false);
                }
            });
        }

        /** 页面切换浅色/深色时通知原生，让顶栏与状态栏一起变（否则选深色后顶上留一条浅色栏） */
        @JavascriptInterface
        public void setTheme(final String theme) {            final boolean dark = "dark".equalsIgnoreCase(theme);
            lastThemeDark = dark;
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    applyBarTheme(dark);
                }
            });
        }
    }

    /** 顶栏 / 状态栏 / 导航栏跟随页面主题 */
    private void applyBarTheme(boolean dark) {
        try {
            int barColor = Color.parseColor(dark ? "#1B1F2B" : "#EDEDED");
            int textColor = Color.parseColor(dark ? "#EDF1F7" : "#191919");
            if (topBar != null) topBar.setBackgroundColor(barColor);
            if (titleView != null) titleView.setTextColor(textColor);
            if (menuBtnView != null) menuBtnView.setTextColor(textColor);
            int flags = dark ? 0 : View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
            if (Build.VERSION.SDK_INT >= 26 && !dark) {
                flags |= View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
            }
            getWindow().getDecorView().setSystemUiVisibility(flags);
            if (Build.VERSION.SDK_INT >= 21) {
                int sys = Color.parseColor(dark ? "#12141C" : "#E6E6E6");
                getWindow().setStatusBarColor(sys);
                getWindow().setNavigationBarColor(sys);
            }
        } catch (Throwable t) {
            Log.w(TAG, "applyBarTheme", t);
        }
    }

    // ------------------------------------------------------------------
    // WebChromeClient：进度、文件上传、全屏
    // ------------------------------------------------------------------

    private class ConsoleChromeClient extends WebChromeClient {

        @Override
        public void onProgressChanged(WebView view, int newProgress) {
            bar.setProgress(newProgress);
            bar.setVisibility(newProgress >= 100 ? View.GONE : View.VISIBLE);
        }

        @Override
        public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                         FileChooserParams params) {
            if (filePathCallback != null) {
                filePathCallback.onReceiveValue(null);
            }
            filePathCallback = callback;
            try {
                Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType("*/*");
                intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
                String[] accept = params == null ? null : params.getAcceptTypes();
                if (accept != null && accept.length > 0) {
                    ArrayList<String> types = new ArrayList<String>();
                    for (String a : accept) {
                        if (a == null) continue;
                        String t = a.trim();
                        if (t.length() == 0) continue;
                        // 有的页面给的是 ".png,.jpg" 这种扩展名，转成 MIME
                        if (t.startsWith(".")) {
                            String m = extToMime(t);
                            if (m != null) types.add(m);
                        } else if (t.contains("/")) {
                            types.add(t);
                        }
                    }
                    if (!types.isEmpty()) {
                        intent.putExtra(Intent.EXTRA_MIME_TYPES, types.toArray(new String[0]));
                        if (types.size() == 1) intent.setType(types.get(0));
                    }
                }
                startActivityForResult(Intent.createChooser(intent, "选择文件"), REQ_FILE_CHOOSER);
                return true;
            } catch (Throwable t) {
                Log.w(TAG, "file chooser failed", t);
                filePathCallback = null;
                toast("打不开文件选择器");
                return false;
            }
        }

        @Override
        public void onShowCustomView(View view, CustomViewCallback callback) {
            if (customView != null) {
                callback.onCustomViewHidden();
                return;
            }
            customView = view;
            customViewCallback = callback;
            originalUiFlags = getWindow().getDecorView().getSystemUiVisibility();

            webParent = (ViewGroup) web.getParent();
            webLp = web.getLayoutParams();
            if (webParent != null) webParent.removeView(web);

            FrameLayout holder = new FrameLayout(MainActivity.this);
            holder.setBackgroundColor(Color.BLACK);
            holder.addView(view, new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            content.addView(holder, new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            view.setTag(holder);

            int flags = View.SYSTEM_UI_FLAG_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                    | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                    | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                    | View.SYSTEM_UI_FLAG_LAYOUT_STABLE;
            getWindow().getDecorView().setSystemUiVisibility(flags);
            // Android 11+ 光靠 SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN 只是"隐藏"状态栏，
            // Activity 内容区并不会延伸进状态栏下方 —— 真机实测：屏幕 831 高而 WebView
            // 只有 792，顶部那 39px 就成了页面盖不到的系统黑边。
            // 必须同时关掉 decor 的 inset 适配，内容才真正铺满全屏。
            if (Build.VERSION.SDK_INT >= 30) {
                getWindow().setDecorFitsSystemWindows(false);
                getWindow().setStatusBarColor(Color.TRANSPARENT);
                getWindow().setNavigationBarColor(Color.TRANSPARENT);
                // 再用"现代版"系统栏接口隐藏一次：部分 ROM 会忽略上面那组旧 flag，
                // 但对 WindowInsetsController 是认的。
                try {
                    android.view.WindowInsetsController ic = getWindow().getInsetsController();
                    if (ic != null) {
                        ic.hide(android.view.WindowInsets.Type.statusBars()
                                | android.view.WindowInsets.Type.navigationBars());
                        ic.setSystemBarsBehavior(android.view.WindowInsetsController
                                .BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
                    }
                } catch (Throwable ignore) {
                }
            }
        }

        @Override
        public void onHideCustomView() {
            if (customView == null) return;
            getWindow().getDecorView().setSystemUiVisibility(originalUiFlags);
            // 退出全屏：把系统栏显示回来即可。**不要再把 decorFits 设回 true** ——
            // 现在整个 App 都是 edge-to-edge（状态栏占位由 applySysInsets 补），
            // 一旦切回 true，insets 会被系统吃掉，原生顶栏就会被状态栏压住。
            if (Build.VERSION.SDK_INT >= 30) {
                try {
                    android.view.WindowInsetsController ic = getWindow().getInsetsController();
                    if (ic != null) {
                        ic.show(android.view.WindowInsets.Type.statusBars()
                                | android.view.WindowInsets.Type.navigationBars());
                    }
                    getWindow().setDecorFitsSystemWindows(true);   // 回到安全区布局
                } catch (Throwable ignore) {
                }
            }
            applyBarTheme(lastThemeDark);
            Object tag = customView.getTag();
            if (tag instanceof ViewGroup) {
                ((ViewGroup) tag).removeAllViews();
                content.removeView((View) tag);
            }
            if (webParent != null && web.getParent() == null) {
                if (webLp != null) {
                    webParent.addView(web, webLp);
                } else {
                    webParent.addView(web);
                }
            }
            customView = null;
            if (customViewCallback != null) {
                try {
                    customViewCallback.onCustomViewHidden();
                } catch (Throwable ignored) {
                }
                customViewCallback = null;
            }
        }
    }

    private static String extToMime(String ext) {
        String e = ext.toLowerCase();
        if (e.equals(".png")) return "image/png";
        if (e.equals(".jpg") || e.equals(".jpeg")) return "image/jpeg";
        if (e.equals(".gif")) return "image/gif";
        if (e.equals(".webp")) return "image/webp";
        if (e.equals(".mp4")) return "video/mp4";
        if (e.equals(".txt") || e.equals(".log") || e.equals(".md")) return "text/plain";
        if (e.equals(".pdf")) return "application/pdf";
        if (e.equals(".json")) return "application/json";
        if (e.equals(".zip")) return "application/zip";
        if (e.equals(".apk")) return "application/vnd.android.package-archive";
        return null;
    }

    // ------------------------------------------------------------------
    // 文件选择结果回填
    // ------------------------------------------------------------------

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == REQ_FILE_CHOOSER) {
            Uri[] results = null;
            if (resultCode == RESULT_OK && data != null) {
                if (data.getClipData() != null) {
                    int n = data.getClipData().getItemCount();
                    ArrayList<Uri> list = new ArrayList<Uri>();
                    for (int i = 0; i < n; i++) {
                        Uri u = data.getClipData().getItemAt(i).getUri();
                        if (u != null) list.add(u);
                    }
                    if (!list.isEmpty()) results = list.toArray(new Uri[0]);
                } else if (data.getData() != null) {
                    results = new Uri[]{data.getData()};
                }
            }
            if (filePathCallback != null) {
                filePathCallback.onReceiveValue(results);
                filePathCallback = null;
            }
            // 返回聊天界面后有些机型会失去焦点 → 整个 WebView 像死掉一样点不动
            try {
                web.setFocusable(true);
                web.requestFocus();
                web.onResume();          // 有的 ROM 从系统选择器回来会暂停 WebView
                web.resumeTimers();
            } catch (Throwable ignored) {
            }
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    // ------------------------------------------------------------------
    // 菜单 / 返回键 / 生命周期
    // ------------------------------------------------------------------

    private android.app.Dialog activeMenu;

    /** 简易底部弹出菜单（不依赖 AlertDialog 的样式，跨 ROM 更稳） */
    private void showMenu() {
        if (activeMenu != null) {
            try {
                activeMenu.dismiss();
            } catch (Throwable ignored) {
            }
            activeMenu = null;
        }
        final android.app.Dialog d = new android.app.Dialog(this,
                android.R.style.Theme_Material_Light_NoActionBar);
        activeMenu = d;

        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (getResources().getDisplayMetrics().density * 8);
        box.setPadding(pad, pad, pad, pad);
        box.setBackgroundColor(Color.WHITE);

        box.addView(menuItem(d, "刷新", new Runnable() {
            @Override
            public void run() {
                loadConsole();
            }
        }));
        box.addView(menuItem(d, "重新设置地址", new Runnable() {
            @Override
            public void run() {
                startActivity(new Intent(MainActivity.this, SetupActivity.class));
            }
        }));
        box.addView(menuItem(d, "检查更新", new Runnable() {
            @Override
            public void run() {
                new UpdateChecker(MainActivity.this, Prefs.getHost(MainActivity.this)).check(false);
            }
        }));
        box.addView(menuItem(d, "关于", new Runnable() {
            @Override
            public void run() {
                toast("手机远程控制台 1.0（com.home.phoneconsole）");
            }
        }));

        d.setContentView(box);
        if (d.getWindow() != null) {
            d.getWindow().setLayout(ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT);
            d.getWindow().setGravity(Gravity.BOTTOM);
        }
        d.show();
    }

    private TextView menuItem(final android.app.Dialog dialog, String text, final Runnable action) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTextSize(16f);
        tv.setTextColor(Color.parseColor("#111111"));
        int p = (int) (getResources().getDisplayMetrics().density * 16);
        tv.setPadding(p, p, p, p);
        tv.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                try {
                    dialog.dismiss();
                } catch (Throwable ignored) {
                }
                if (activeMenu == dialog) activeMenu = null;
                action.run();
            }
        });
        return tv;
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            // 全屏播放中先退出全屏
            if (customView != null) {
                ConsoleChromeClient c = (ConsoleChromeClient) web.getWebChromeClient();
                if (c != null) c.onHideCustomView();
                return true;
            }
            if (web != null && web.canGoBack()) {
                web.goBack();
                return true;
            }
            long now = System.currentTimeMillis();
            if (now - lastBackTime < 2000) {
                // finish() 只结束 MainActivity，任务里可能还留着空壳 → 先看到"空白界面"。
                // finishAffinity 把整个任务清掉，直接回桌面。
                finishAffinity();
            } else {
                lastBackTime = now;
                toast("再按一次返回退出");
            }
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
    }

    @Override
    public void onAttachedToWindow() {
        super.onAttachedToWindow();
    }

    @Override
    protected void onResume() {
        super.onResume();
        // 从别的 App 回来时，部分 ROM 会把 WebView 的渲染层丢掉 → 白屏。
        // 这里主动恢复渲染与计时器，并在页面异常时重新加载一次。
        try {
            if (web != null) {
                web.onResume();
                web.resumeTimers();
                web.invalidate();
                if (web.getUrl() == null) loadConsole();
            }
        } catch (Throwable ignored) {
        }
        // 检查更新：连上以后自动静默查一次（失败只记录，不打扰）
        if (web != null && Prefs.isConfigured(this)) {
            new UpdateChecker(this, Prefs.getHost(this)).check(true);
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (web != null) {
            try {
                web.onPause();
            } catch (Throwable ignored) {
            }
        }
    }

    @Override
    protected void onDestroy() {
        try {
            if (web != null) {
                if (web.getParent() instanceof ViewGroup) {
                    ((ViewGroup) web.getParent()).removeView(web);
                }
                web.destroy();
            }
        } catch (Throwable t) {
            Log.w(TAG, "destroy webview", t);
        }
        super.onDestroy();
    }

    private void toast(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show();
    }
}
