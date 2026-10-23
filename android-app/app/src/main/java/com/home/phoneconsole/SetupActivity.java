package com.home.phoneconsole;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.net.ConnectivityManager;
import android.net.Uri;
import android.net.LinkAddress;
import android.net.LinkProperties;
import android.net.Network;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.text.InputType;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.net.URL;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Enumeration;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

import com.google.zxing.BinaryBitmap;
import com.google.zxing.LuminanceSource;
import com.google.zxing.MultiFormatReader;
import com.google.zxing.RGBLuminanceSource;
import com.google.zxing.Result;
import com.google.zxing.common.HybridBinarizer;

/**
 * 界面 1：连接设置。
 * 地址输入 + PIN 输入 + 扫描局域网 + 从剪贴板粘贴 + 历史地址 + 保存并连接。
 * 所有 UI 由代码创建（不依赖 layout xml），全部原生 API，无第三方依赖。
 */
public class SetupActivity extends Activity {

    private static final String TAG = "SetupActivity";
    /** 控制台默认端口 */
    private static final int DEFAULT_PORT = 8787;
    /** 局域网扫描单机超时（毫秒） */
    private static final int SCAN_TIMEOUT_MS = 500;
    /** 扫描并发线程数：254 个地址，太快会被系统/路由器丢包 */
    private static final int SCAN_THREADS = 32;
    /** 扫码：实时 / 拍照 / 从相册选图 的请求码 */
    private static final int REQ_QR_CAPTURE = 1001;
    private static final int REQ_QR_PICK = 1002;
    private static final int REQ_QR_LIVE = 1003;

    private EditText hostInput;
    private EditText pinInput;
    private TextView statusText;
    private ProgressBar progress;
    private Button scanBtn;
    private Button pasteBtn;
    private LinearLayout historyBox;
    /** 相机写入二维码照片的目标 Uri（content://，Android 7+ 不能传 file://） */
    private Uri qrOutputUri;

    private final Handler ui = new Handler(Looper.getMainLooper());
    private ExecutorService scanPool;
    private volatile boolean scanning = false;
    private final AtomicBoolean cancelled = new AtomicBoolean(false);

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        final boolean firstRun = !Prefs.isConfigured(this);

        applyDarkSystemBars();

        ScrollView scroll = new ScrollView(this);
        scroll.setBackground(pageBackdrop());
        scroll.setFillViewport(true);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(18);
        root.setPadding(pad, dp(26), pad, dp(26));
        scroll.addView(root, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        // ---- 品牌头部 ----
        android.widget.ImageView appIcon = new android.widget.ImageView(this);
        appIcon.setImageResource(R.mipmap.ic_launcher);
        LinearLayout.LayoutParams iconLp = new LinearLayout.LayoutParams(dp(72), dp(72));
        iconLp.gravity = Gravity.CENTER_HORIZONTAL;
        root.addView(appIcon, iconLp);

        TextView title = new TextView(this);
        title.setText(firstRun ? "连接你的电脑" : "重新设置地址");
        title.setTextSize(23f);
        title.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        title.setTextColor(Color.parseColor("#0D0D0F"));
        title.setGravity(Gravity.CENTER);
        title.setPadding(0, dp(14), 0, 0);
        root.addView(title);

        TextView sub = new TextView(this);
        sub.setText("在手机上远程操作电脑里的 DSH 智能体");
        sub.setTextSize(12.5f);
        sub.setTextColor(Color.parseColor("#6B7280"));
        sub.setGravity(Gravity.CENTER);
        sub.setPadding(0, dp(7), 0, dp(18));
        root.addView(sub);

        // ---- 上次启动崩溃摘要（深色告警条） ----
        try {
            java.io.File cf = new java.io.File(getFilesDir(), "last-crash.txt");
            if (cf.exists()) {
                String txt = readTextFile(cf);
                if (txt != null && txt.length() > 0) {
                    TextView crash = new TextView(this);
                    crash.setTextSize(11.5f);
                    crash.setTextColor(Color.parseColor("#FFB4A8"));
                    crash.setBackground(roundBg("#2A1618", 12, "#5A2A2C", 1));
                    crash.setPadding(dp(13), dp(11), dp(13), dp(11));
                    crash.setText("上次启动出错（可截图反馈）：\n" + txt);
                    LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(
                            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
                    clp.bottomMargin = dp(14);
                    root.addView(crash, clp);
                }
            }
        } catch (Throwable ignored) {
        }

        // ---- 连接卡片 ----
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setBackground(roundBg("#FFFFFF", 20, "#EAECF2", 1));
        card.setPadding(dp(16), dp(16), dp(16), dp(16));
        root.addView(card, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        card.addView(sectionLabel("控制台地址"));
        hostInput = new EditText(this);
        hostInput.setHint("192.168.1.23:8787 或 https://…trycloudflare.com");
        hostInput.setSingleLine(true);
        hostInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        hostInput.setText(Prefs.getHost(this));
        styleInput(hostInput);
        card.addView(hostInput);

        card.addView(sectionLabel("PIN（可留空）"));
        pinInput = new EditText(this);
        pinInput.setHint("8 位数字，留空则在网页里输入");
        pinInput.setSingleLine(true);
        pinInput.setInputType(InputType.TYPE_CLASS_NUMBER);
        pinInput.setText(Prefs.getPin(this));
        styleInput(pinInput);
        card.addView(pinInput);

        Button saveBtn = new Button(this);
        saveBtn.setText("连接");
        stylePrimary(saveBtn);
        saveBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                saveAndConnect();
            }
        });
        LinearLayout.LayoutParams slp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(48));
        slp.topMargin = dp(18);
        card.addView(saveBtn, slp);

        // 扫码 / 扫描局域网
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout.LayoutParams rlp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        rlp.topMargin = dp(10);
        card.addView(row, rlp);

        Button qrBtn = new Button(this);
        qrBtn.setText("扫码连接");
        styleOutline(qrBtn);
        qrBtn.setLayoutParams(new LinearLayout.LayoutParams(0, dp(44), 1f));
        qrBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                startQrScan();
            }
        });
        row.addView(qrBtn);

        scanBtn = new Button(this);
        scanBtn.setText("扫描局域网");
        styleOutline(scanBtn);
        LinearLayout.LayoutParams scanLp = new LinearLayout.LayoutParams(0, dp(44), 1f);
        scanLp.leftMargin = dp(10);
        scanBtn.setLayoutParams(scanLp);
        scanBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (scanning) {
                    cancelScan();
                } else {
                    startScan();
                }
            }
        });
        row.addView(scanBtn);

        // 启动时是否先显示网页登录页
        final android.widget.CheckBox requireLoginCb = new android.widget.CheckBox(this);
        requireLoginCb.setText("启动时先显示登录页（更安全）");
        requireLoginCb.setTextSize(12.5f);
        requireLoginCb.setTextColor(Color.parseColor("#6B7280"));
        requireLoginCb.setChecked(Prefs.getRequireLogin(this));
        requireLoginCb.setPadding(0, dp(10), 0, 0);
        requireLoginCb.setOnCheckedChangeListener(new android.widget.CompoundButton.OnCheckedChangeListener() {
            @Override
            public void onCheckedChanged(android.widget.CompoundButton buttonView, boolean isChecked) {
                Prefs.setRequireLogin(SetupActivity.this, isChecked);
            }
        });
        card.addView(requireLoginCb);

        // 粘贴（文字按钮）
        TextView paste = new TextView(this);
        paste.setText("从剪贴板粘贴");
        paste.setTextSize(13f);
        paste.setTextColor(Color.parseColor("#4D6BFE"));
        paste.setGravity(Gravity.CENTER);
        paste.setPadding(0, dp(14), 0, dp(4));
        paste.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                pasteFromClipboard();
            }
        });
        card.addView(paste);

        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setMax(254);
        progress.setVisibility(View.GONE);
        LinearLayout.LayoutParams plp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(3));
        plp.topMargin = dp(8);
        card.addView(progress, plp);

        statusText = new TextView(this);
        statusText.setTextSize(12.5f);
        statusText.setTextColor(Color.parseColor("#6B7280"));
        statusText.setPadding(0, dp(10), 0, 0);
        statusText.setVisibility(View.GONE);
        card.addView(statusText);

        // ---- 最近使用 ----
        historyBox = new LinearLayout(this);
        historyBox.setOrientation(LinearLayout.VERTICAL);
        LinearLayout.LayoutParams hlp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        hlp.topMargin = dp(18);
        root.addView(historyBox, hlp);

        // ---- 折叠帮助 ----
        final TextView helpTitle = new TextView(this);
        helpTitle.setText("怎么连接？点开看说明");
        helpTitle.setTextSize(12.5f);
        helpTitle.setTextColor(Color.parseColor("#6B7280"));
        helpTitle.setPadding(0, dp(20), 0, dp(8));
        root.addView(helpTitle);

        final TextView help = new TextView(this);
        help.setTextSize(12f);
        help.setTextColor(Color.parseColor("#8A8F9C"));
        help.setLineSpacing(dp(3), 1.15f);
        help.setText("1. 桌面端打开「手机远程控制台」，点「启动」，用本页「扫码连接」扫面板上的二维码\n"
                + "2. 同一 Wi-Fi 下也可以点「扫描局域网」自动发现电脑（会扫常见网段）\n"
                + "3. 公网隧道地址直接粘贴 https://…trycloudflare.com/?pin=xxxxxxxx\n"
                + "4. PIN 可留空，进入网页后再输入；只填 IP 时会自动补 http:// 与 :8787");
        help.setVisibility(View.GONE);
        root.addView(help);
        helpTitle.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                boolean show = help.getVisibility() != View.VISIBLE;
                help.setVisibility(show ? View.VISIBLE : View.GONE);
                helpTitle.setText(show ? "收起说明" : "怎么连接？点开看说明");
            }
        });

        // ---- 页脚版本号 ----
        TextView verText = new TextView(this);
        String verName = "";
        try {
            verName = getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (Throwable ignore) {
        }
        verText.setText("手机远程控制台 · v" + (verName == null ? "?" : verName));
        verText.setTextSize(11f);
        verText.setTextColor(Color.parseColor("#B4B8C2"));
        verText.setGravity(Gravity.CENTER);
        verText.setPadding(0, dp(24), 0, dp(6));
        root.addView(verText);

        setContentView(scroll);

        refreshHistory();
        if (firstRun) {
            setStatus("还没有地址：可以「扫码连接」或用「扫描局域网」自动发现");
            // 逻辑优化：首屏自动扫一次局域网（有线/同一 Wi-Fi 时基本一步到位）
            ui.postDelayed(new Runnable() {
                @Override
                public void run() {
                    try {
                        if (!isFinishing() && !scanning) startScan();
                    } catch (Throwable ignored) {
                    }
                }
            }, 700);
            // 剪贴板里已经有一整条地址 → 直接提示填入
            ui.postDelayed(new Runnable() {
                @Override
                public void run() {
                    try {
                        String txt = clipboardText();
                        if (txt != null) {
                            String h = normalizeHost(txt);
                            if (h != null && !h.equals(hostInput.getText().toString().trim())) {
                                setStatus("剪贴板里有地址：" + h + "（点「从剪贴板粘贴」填入）");
                            }
                        }
                    } catch (Throwable ignored) {
                    }
                }
            }, 900);
        } else {
            setStatus("当前地址：" + Prefs.getHost(this));
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        refreshHistory();
    }

    @Override
    protected void onDestroy() {
        cancelled.set(true);
        stopPool();
        super.onDestroy();
    }

    // ------------------------------------------------------------------
    // UI 小工具
    // ------------------------------------------------------------------

    private int dp(int v) {
        return Math.round(getResources().getDisplayMetrics().density * v);
    }

    // ------------------------------------------------------------------
    // 外观辅助：圆角背景 / 输入框 / 主次按钮（全部代码绘制，不引第三方库）
    // ------------------------------------------------------------------

    /** 圆角底色；stroke 传 null 表示不描边 */
    private android.graphics.drawable.GradientDrawable roundBg(String color, float radiusDp,
                                                               String stroke, int strokeDp) {
        android.graphics.drawable.GradientDrawable d = new android.graphics.drawable.GradientDrawable();
        d.setColor(Color.parseColor(color));
        d.setCornerRadius(dp((int) radiusDp));
        if (stroke != null && strokeDp > 0) {
            d.setStroke(dp(strokeDp), Color.parseColor(stroke));
        }
        return d;
    }

    /** 带按压水波纹的圆角背景（API 21+ 才有波纹，低版本退化为纯圆角） */
    private android.graphics.drawable.Drawable rippleBg(String color, float radiusDp,
                                                        String stroke, int strokeDp) {
        android.graphics.drawable.GradientDrawable base = roundBg(color, radiusDp, stroke, strokeDp);
        if (Build.VERSION.SDK_INT >= 21) {
            return new android.graphics.drawable.RippleDrawable(
                    android.content.res.ColorStateList.valueOf(0x1F000000), base, null);
        }
        return base;
    }

    /** 深色渐变底：顶部 #0E141C → 底部 #070A0E */
    private android.graphics.drawable.Drawable pageBackdrop() {
        // 白 → 极浅灰，和对话页（白底黑字）一致
        android.graphics.drawable.GradientDrawable d = new android.graphics.drawable.GradientDrawable(
                android.graphics.drawable.GradientDrawable.Orientation.TOP_BOTTOM,
                new int[]{Color.parseColor("#FFFFFF"), Color.parseColor("#F4F6FB")});
        return d;
    }

    /** 状态栏/导航栏切成深色（浅色图标） */
    private void applyDarkSystemBars() {
        try {
            getWindow().setStatusBarColor(Color.WHITE);
            getWindow().setNavigationBarColor(Color.WHITE);
            if (Build.VERSION.SDK_INT >= 23) {
                // 白底浅色状态栏 → 用深色图标
                getWindow().getDecorView().setSystemUiVisibility(
                        android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
            }
        } catch (Throwable ignored) {
        }
    }

    /** 分组小标题：大写感 + 字距 */
    private TextView sectionLabel(String text) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTextSize(11f);
        tv.setTextColor(Color.parseColor("#8A8F9C"));
        tv.setPadding(0, dp(14), 0, dp(6));
        if (Build.VERSION.SDK_INT >= 21) tv.setLetterSpacing(0.06f);
        return tv;
    }

    /** 输入框：深色底 + 发丝描边 + 聚焦薄荷描边 */
    private void styleInput(final EditText e) {
        e.setTextSize(15f);
        e.setTextColor(Color.parseColor("#0D0D0F"));
        e.setHintTextColor(Color.parseColor("#A6ABB8"));
        final android.graphics.drawable.Drawable normal = roundBg("#FFFFFF", 13, "#E5E8EF", 1);
        final android.graphics.drawable.Drawable focus = roundBg("#FFFFFF", 13, "#4D6BFE", 1);
        e.setBackground(normal);
        e.setPadding(dp(14), dp(13), dp(14), dp(13));
        e.setOnFocusChangeListener(new View.OnFocusChangeListener() {
            @Override
            public void onFocusChange(View v, boolean hasFocus) {
                e.setBackground(hasFocus ? focus : normal);
            }
        });
    }

    /** 主按钮：薄荷渐变 + 深色字（发光的品牌按钮） */
    private void stylePrimary(Button b) {
        b.setAllCaps(false);
        b.setTextSize(16f);
        b.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        b.setTextColor(Color.WHITE);
        android.graphics.drawable.GradientDrawable g = new android.graphics.drawable.GradientDrawable(
                android.graphics.drawable.GradientDrawable.Orientation.LEFT_RIGHT,
                new int[]{Color.parseColor("#5B7BFF"), Color.parseColor("#4D6BFE")});
        g.setCornerRadius(dp(14));
        if (Build.VERSION.SDK_INT >= 21) {
            b.setBackground(new android.graphics.drawable.RippleDrawable(
                    android.content.res.ColorStateList.valueOf(0x33000000), g, null));
            b.setElevation(dp(3));
        } else {
            b.setBackground(g);
        }
        b.setPadding(dp(10), dp(12), dp(10), dp(12));
    }

    /** 次按钮：深色底 + 发丝描边 + 薄荷字 */
    private void styleOutline(Button b) {
        b.setAllCaps(false);
        b.setTextSize(13.5f);
        b.setTextColor(Color.parseColor("#0D0D0F"));
        b.setBackground(rippleBg("#FFFFFF", 12, "#E5E8EF", 1));
        b.setPadding(dp(6), dp(10), dp(6), dp(10));
    }

    private TextView label(String text) {
        return sectionLabel(text);
    }

    private void toast(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show();
    }

    private void setStatus(String msg) {
        statusText.setText(msg);
        // 空内容就整块隐藏（首屏不该出现一个没有任何文字的空白块）
        statusText.setVisibility((msg == null || msg.length() == 0) ? View.GONE : View.VISIBLE);
    }

    private void refreshHistory() {
        if (historyBox == null) return;
        historyBox.removeAllViews();
        List<String> hist = Prefs.getHistory(this);
        if (hist.isEmpty()) {
            TextView empty = new TextView(this);
            empty.setText("暂无历史地址");
            empty.setTextSize(12f);
            empty.setTextColor(Color.parseColor("#A6ABB8"));
            empty.setPadding(dp(2), dp(8), 0, dp(4));
            historyBox.addView(empty);
            return;
        }
        TextView cap = new TextView(this);
        cap.setText("最近使用");
        cap.setTextSize(11f);
        cap.setTextColor(Color.parseColor("#8A8F9C"));
        cap.setPadding(dp(2), 0, 0, dp(8));
        historyBox.addView(cap);

        for (final String h : hist) {
            TextView b = new TextView(this);
            b.setText(h);
            b.setTextSize(13f);
            b.setTextColor(Color.parseColor("#0D0D0F"));
            b.setGravity(Gravity.CENTER_VERTICAL);
            b.setBackground(rippleBg("#F7F8FB", 12, "#EAECF2", 1));
            b.setPadding(dp(14), dp(12), dp(14), dp(12));
            b.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    hostInput.setText(h);
                    setStatus("已填入：" + h);
                }
            });
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            lp.topMargin = dp(6);
            historyBox.addView(b, lp);
        }
    }

    // ------------------------------------------------------------------
    // 地址解析与保存
    // ------------------------------------------------------------------

    /**
     * 把用户输入整理成 host:port 形式。
     * 支持：192.168.1.23 / 192.168.1.23:8787 / http://192.168.1.23:8787 / 带路径或 ?pin= 的完整链接。
     * 返回 null 表示输入非法。
     */
    static String normalizeHost(String raw) {
        if (raw == null) return null;
        String s = raw.trim();
        if (s.length() == 0) return null;
        // 记下 scheme 再去掉它：https 的地址（公网隧道）绝不能补 :8787
        String scheme = null;
        int idx = s.indexOf("://");
        if (idx >= 0) {
            scheme = s.substring(0, idx).toLowerCase();
            s = s.substring(idx + 3);
        }
        // 去掉路径 / 查询 / 参数
        int cut = s.length();
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '/' || c == '?' || c == '#' || c == ' ' || c == '\t') {
                cut = i;
                break;
            }
        }
        s = s.substring(0, cut);
        // 去掉 user:pass@
        int at = s.lastIndexOf('@');
        if (at >= 0) s = s.substring(at + 1);
        if (s.length() == 0) return null;

        String host;
        String port = null;
        if (s.startsWith("[")) { // IPv6 字面量
            int close = s.indexOf(']');
            if (close < 0) return null;
            host = s.substring(1, close);
            String rest = s.substring(close + 1);
            if (rest.startsWith(":") && rest.length() > 1) port = rest.substring(1);
        } else {
            int colon = s.lastIndexOf(':');
            if (colon >= 0 && s.indexOf(':') == colon) {
                host = s.substring(0, colon);
                port = s.substring(colon + 1);
            } else {
                host = s; // 纯 IPv6 或纯主机名
            }
        }
        host = host.trim();
        if (host.length() == 0) return null;
        if (port != null) {
            port = port.trim();
            if (port.length() == 0) {
                port = null;
            } else {
                try {
                    int p = Integer.parseInt(port);
                    if (p <= 0 || p > 65535) return null;
                    port = String.valueOf(p);
                } catch (NumberFormatException e) {
                    return null;
                }
            }
        }
        // IPv6 字面量拼端口时必须带方括号，否则 ::1:8787 会被当成主机名
        String hostOut = host.indexOf(':') >= 0 ? "[" + host + "]" : host;
        // 公网隧道域名（trycloudflare / ngrok / ...）永远走 https 的 443 端口。
        // 老版本把它当局域网地址、在没端口时补上 :8787，于是
        // xxx.trycloudflare.com:8787 直接 ERR_CONNECTION_TIMED_OUT（真机踩过）。
        if (isTunnelHost(host)) {
            return "https://" + host;
        }
        if (port == null) {
            if ("https".equals(scheme)) {
                return "https://" + hostOut;         // 显式 https 且没写端口 -> 443
            }
            // 裸域名（有点号、又不是 IP 字面量）基本是隧道/公网域名 -> 走 https；
            // 局域网 IP / 单标签主机名照旧补 8787
            if (scheme == null && host.indexOf('.') >= 0 && !isIpLiteral(host)) {
                return "https://" + hostOut;
            }
            port = String.valueOf(DEFAULT_PORT);
        }
        if ("https".equals(scheme)) {
            return "https://" + hostOut + ":" + port;   // 显式 https + 显式端口
        }
        return hostOut + ":" + port;
    }

    /** 已知的公网隧道域名后缀：这些一律 https + 443，不能补/保留 :8787 */
    private static final String[] TUNNEL_SUFFIXES = {
            ".trycloudflare.com", ".ngrok-free.app", ".ngrok.io", ".ngrok.app",
            ".natappfree.cc", ".cpolar.top", ".cpolar.cn", ".loca.lt", ".serveo.net",
    };

    private static boolean isTunnelHost(String host) {
        if (host == null) return false;
        String h = host.toLowerCase();
        for (String suf : TUNNEL_SUFFIXES) {
            if (h.endsWith(suf)) return true;
        }
        return false;
    }

    /** 是不是 IP 字面量（IPv4/IPv6）—— 用来区分「局域网 IP」与「公网域名」 */
    private static boolean isIpLiteral(String h) {
        if (h == null || h.length() == 0) return false;
        if (h.indexOf(':') >= 0) return true;                  // IPv6
        if (!h.matches("[0-9.]+")) return false;
        String[] parts = h.split("\\.");
        if (parts.length != 4) return false;
        for (String p : parts) {
            try {
                int v = Integer.parseInt(p);
                if (v < 0 || v > 255) return false;
            } catch (NumberFormatException e) {
                return false;
            }
        }
        return true;
    }

    /**
     * 迁移历史保存的地址：老版本可能把隧道域名存成了 host:8787，
     * 这里改回 https://域名，用户升级后不必手动重填。其它地址原样返回。
     */
    static String migrateStoredHost(String host) {
        if (host == null) return "";
        String h = host.trim();
        if (h.length() == 0) return "";
        boolean hasScheme = h.startsWith("http://") || h.startsWith("https://");
        int idx = h.indexOf("://");
        String rest = hasScheme ? h.substring(idx + 3) : h;
        int slash = rest.indexOf('/');
        String head = slash >= 0 ? rest.substring(0, slash) : rest;
        int colon = head.lastIndexOf(':');
        if (colon > 0 && isTunnelHost(head.substring(0, colon))) {
            return "https://" + head.substring(0, colon);
        }
        if (isTunnelHost(head)) {
            return "https://" + head;
        }
        return h;
    }

    /** 由 host:port 生成可在 WebView 中加载的 http URL；pin 为空则只加载根路径 */
    static String buildUrl(String host, String pin) {
        String base = host;
        if (!base.startsWith("http://") && !base.startsWith("https://")) {
            base = "http://" + base;
        }
        if (pin != null && pin.length() > 0) {
            return base + (base.contains("?") ? "&" : "/?") + "pin=" + pin;
        }
        return base + "/";
    }

    private static String readTextFile(java.io.File f) {
        try {
            java.io.FileInputStream in = new java.io.FileInputStream(f);
            byte[] buf = new byte[(int) f.length()];
            int n = in.read(buf);
            in.close();
            return n <= 0 ? "" : new String(buf, 0, n, "UTF-8");
        } catch (Throwable t) {
            return "";
        }
    }

    private void saveAndConnect() {
        String host = normalizeHost(hostInput.getText().toString());
        if (host == null) {
            toast("地址看起来不对，示例：192.168.1.23:8787");
            return;
        }
        String pin = pinInput.getText().toString().trim();
        if (pin.length() > 0 && (pin.length() != 8 || !pin.matches("[0-9]{8}"))) {
            toast("PIN 需要是 8 位数字，或者留空");
            return;
        }
        hostInput.setText(host);
        Prefs.save(this, host, pin);
        refreshHistory();
        startActivity(new Intent(this, MainActivity.class));
        finish();
    }

    // ------------------------------------------------------------------
    // 扫码：拍照（或从相册选图）后用 ZXing 解码，自动填地址与 PIN
    // ------------------------------------------------------------------

    /** 「扫码识别二维码」：优先实时扫码（相机预览 + 连续识别，对齐系统扫码体验） */
    private void startQrScan() {
        if (!getPackageManager().hasSystemFeature(PackageManager.FEATURE_CAMERA_ANY)) {
            startPhotoScan();          // 没相机：直接退回拍照/选图
            return;
        }
        try {
            startActivityForResult(new Intent(this, ScannerActivity.class), REQ_QR_LIVE);
        } catch (Throwable t) {
            Log.w(TAG, "startQrScan", t);
            startPhotoScan();
        }
    }

    /** 退回方案：交给系统相机拍一张再解码（相机不可用 / 没授权时用） */
    private void startPhotoScan() {
        try {
            File dir = new File(getCacheDir(), "qr");
            if (!dir.exists()) dir.mkdirs();
            File out = new File(dir, "scan_" + System.currentTimeMillis() + ".jpg");
            qrOutputUri = QrImageProvider.getUriForFile(this, out);
            if (qrOutputUri == null) {
                toast("无法创建扫码临时文件");
                return;
            }
            Intent capture = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
            capture.putExtra(MediaStore.EXTRA_OUTPUT, qrOutputUri);
            capture.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
            try {
                startActivityForResult(capture, REQ_QR_CAPTURE);
            } catch (ActivityNotFoundException noCamera) {
                // 没有相机 App（平板/精简 ROM）：退回从相册或文件里选一张二维码图片
                Intent pick = new Intent(Intent.ACTION_GET_CONTENT);
                pick.setType("image/*");
                pick.addCategory(Intent.CATEGORY_OPENABLE);
                try {
                    startActivityForResult(Intent.createChooser(pick, "选择二维码图片"), REQ_QR_PICK);
                } catch (ActivityNotFoundException noPicker) {
                    toast("这台设备没有可用的相机或相册");
                }
            }
        } catch (Throwable t) {
            Log.w(TAG, "startQrScan failed", t);
            toast("打不开相机：" + t.getClass().getSimpleName());
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_QR_LIVE) {
            String text = data == null ? null : data.getStringExtra(ScannerActivity.EXTRA_TEXT);
            String err = data == null ? null : data.getStringExtra(ScannerActivity.EXTRA_ERROR);
            if (resultCode == RESULT_OK && text != null && text.trim().length() > 0) {
                applyScannedText(text);
            } else if (err != null) {
                // 相机打不开 / 没授权：自动退回拍照识别，别让用户卡在这里
                setStatus(err + "，已切回拍照识别");
                startPhotoScan();
            } else {
                setStatus("已取消扫码");
            }
            return;
        }
        if (requestCode != REQ_QR_CAPTURE && requestCode != REQ_QR_PICK) return;
        if (resultCode != RESULT_OK) {
            setStatus("已取消扫码");
            return;
        }
        Uri uri = (requestCode == REQ_QR_CAPTURE) ? qrOutputUri
                : (data == null ? null : data.getData());
        if (uri == null) {
            setStatus("没拿到图片");
            return;
        }
        setStatus("正在识别二维码…");
        final Uri target = uri;
        new Thread(new Runnable() {
            @Override
            public void run() {
                final String text = decodeQr(target);
                ui.post(new Runnable() {
                    @Override
                    public void run() {
                        if (text == null || text.trim().length() == 0) {
                            setStatus("没识别出二维码：靠近一点、对准、光线亮些再试一次");
                            toast("识别失败");
                        } else {
                            applyScannedText(text);
                        }
                    }
                });
            }
        }, "qr-decode").start();
    }

    /** 用 ZXing 解码；支持相机照片与相册图片，识别所有常见码制 */
    private String decodeQr(Uri uri) {
        try {
            Bitmap bmp = loadScaledBitmap(uri, 1600);
            if (bmp == null) return null;
            int w = bmp.getWidth();
            int h = bmp.getHeight();
            int[] px = new int[w * h];
            bmp.getPixels(px, 0, w, 0, 0, w, h);
            bmp.recycle();
            LuminanceSource src = new RGBLuminanceSource(w, h, px);
            BinaryBitmap bm = new BinaryBitmap(new HybridBinarizer(src));
            Result r = new MultiFormatReader().decodeWithState(bm);
            return r == null ? null : r.getText();
        } catch (Throwable t) {
            Log.w(TAG, "decodeQr failed", t);   // NotFoundException 属正常情况，不必打扰用户
            return null;
        }
    }

    /** 解码前先按需降采样，避免大照片把内存吃爆（二维码 1600px 足够识别） */
    private Bitmap loadScaledBitmap(Uri uri, int maxSide) {
        try {
            BitmapFactory.Options bounds = new BitmapFactory.Options();
            bounds.inJustDecodeBounds = true;
            InputStream is = getContentResolver().openInputStream(uri);
            if (is == null) return null;
            try {
                BitmapFactory.decodeStream(is, null, bounds);
            } finally {
                is.close();
            }
            int sample = 1;
            while (bounds.outWidth / (sample * 2) >= maxSide
                    || bounds.outHeight / (sample * 2) >= maxSide) {
                sample *= 2;
            }
            BitmapFactory.Options opts = new BitmapFactory.Options();
            opts.inSampleSize = sample;
            InputStream is2 = getContentResolver().openInputStream(uri);
            if (is2 == null) return null;
            try {
                return BitmapFactory.decodeStream(is2, null, opts);
            } finally {
                is2.close();
            }
        } catch (Throwable t) {
            Log.w(TAG, "loadScaledBitmap failed", t);
            return null;
        }
    }

    /** 扫码结果 → 地址 / PIN（与「从剪贴板粘贴」同一套解析规则） */
    private void applyScannedText(String text) {
        String s = text == null ? "" : text.trim();
        String pin = extractPin(s);
        String host = normalizeHost(s);
        if (host == null) {
            setStatus("识别到内容，但不是控制台地址：" + s);
            toast("二维码内容不是控制台地址");
            return;
        }
        hostInput.setText(host);
        final boolean hasPin = pin != null && pin.length() > 0;
        if (hasPin) {
            pinInput.setText(pin);
            setStatus("扫码成功：地址 " + host + "，PIN " + pin + "，正在连接…");
        } else {
            setStatus("扫码成功：地址 " + host + "（二维码里没有 PIN，留空即可）");
        }
        // 扫码即连：不再要求用户再点一次「连接」、也不用重新输 PIN
        ui.postDelayed(new Runnable() {
            @Override
            public void run() {
                try {
                    if (!isFinishing()) saveAndConnect();
                } catch (Throwable ignored) {
                }
            }
        }, hasPin ? 260 : 400);
    }

    /** 从链接里取 pin：pin= 后面最多 8 位数字 */
    private static String extractPin(String text) {
        int pi = text.indexOf("pin=");
        if (pi < 0) return null;
        String rest = text.substring(pi + 4);
        StringBuilder digits = new StringBuilder();
        for (int i = 0; i < rest.length() && digits.length() < 8; i++) {
            char c = rest.charAt(i);
            if (c >= '0' && c <= '9') {
                digits.append(c);
            } else {
                break;
            }
        }
        return digits.length() > 0 ? digits.toString() : null;
    }

    // ------------------------------------------------------------------
    // 按钮 B：从剪贴板粘贴
    // ------------------------------------------------------------------

    private String clipboardText() {
        try {
            ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            if (cm == null || !cm.hasPrimaryClip() || cm.getPrimaryClip() == null) return null;
            if (cm.getPrimaryClip().getItemCount() < 1) return null;
            CharSequence cs = cm.getPrimaryClip().getItemAt(0).coerceToText(this);
            return cs == null ? null : cs.toString().trim();
        } catch (Throwable t) {
            return null;
        }
    }

    private void pasteFromClipboard() {
        try {
            ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            if (cm == null || !cm.hasPrimaryClip() || cm.getPrimaryClip() == null
                    || cm.getPrimaryClip().getItemCount() == 0) {
                toast("剪贴板是空的");
                return;
            }
            CharSequence cs = cm.getPrimaryClip().getItemAt(0).coerceToText(this);
            String text = cs == null ? "" : cs.toString().trim();
            if (text.length() == 0) {
                toast("剪贴板是空的");
                return;
            }
            // 从链接里拆 PIN
            String pin = null;
            int pi = text.indexOf("pin=");
            if (pi >= 0) {
                String rest = text.substring(pi + 4);
                StringBuilder digits = new StringBuilder();
                for (int i = 0; i < rest.length() && digits.length() < 8; i++) {
                    char c = rest.charAt(i);
                    if (c >= '0' && c <= '9') {
                        digits.append(c);
                    } else {
                        break;
                    }
                }
                if (digits.length() > 0) pin = digits.toString();
            }
            String host = normalizeHost(text);
            if (host == null) {
                toast("剪贴板内容里没找到地址");
                setStatus("剪贴板内容无法识别，请确认形如 http://192.168.1.23:8787/?pin=12345678");
                return;
            }
            hostInput.setText(host);
            if (pin != null && pin.length() > 0) {
                pinInput.setText(pin);
                setStatus("已从剪贴板识别：地址 " + host + "，PIN " + pin);
            } else {
                setStatus("已从剪贴板识别地址：" + host + "（没找到 PIN，可留空）");
            }
        } catch (Throwable t) {
            // 某些 ROM 在后台读剪贴板会抛异常，不能让它崩
            Log.w(TAG, "paste failed", t);
            toast("读取剪贴板失败：" + t.getClass().getSimpleName());
        }
    }

    // ------------------------------------------------------------------
    // 按钮 A：扫描局域网
    // ------------------------------------------------------------------

    /** 本机 Wi-Fi IPv4，例如 192.168.1.55；取不到返回 null */
    private String localWifiIpv4() {
        // 1) API 21+：通读所有链路，优先 wlan 接口
        try {
            ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
            if (cm != null) {
                Network[] nets = cm.getAllNetworks();
                if (nets != null) {
                    for (Network n : nets) {
                        LinkProperties lp = cm.getLinkProperties(n);
                        if (lp == null) continue;
                        String iface = lp.getInterfaceName();
                        if (iface == null || !iface.startsWith("wlan")) continue;
                        for (LinkAddress la : lp.getLinkAddresses()) {
                            InetAddress a = la.getAddress();
                            if (a instanceof Inet4Address && !a.isLoopbackAddress()) {
                                return a.getHostAddress();
                            }
                        }
                    }
                }
            }
        } catch (Throwable t) {
            Log.w(TAG, "getAllNetworks failed", t);
        }
        // 2) WifiManager 兜底
        try {
            WifiManager wm = (WifiManager) getApplicationContext()
                    .getSystemService(Context.WIFI_SERVICE);
            if (wm != null && wm.getConnectionInfo() != null) {
                int ip = wm.getConnectionInfo().getIpAddress();
                if (ip != 0) {
                    return (ip & 0xFF) + "." + ((ip >> 8) & 0xFF) + "."
                            + ((ip >> 16) & 0xFF) + "." + ((ip >> 24) & 0xFF);
                }
            }
        } catch (Throwable t) {
            Log.w(TAG, "WifiManager failed", t);
        }
        // 3) 网卡枚举兜底（部分机型前面两条都给不出）
        try {
            Enumeration<NetworkInterface> ifaces = NetworkInterface.getNetworkInterfaces();
            if (ifaces != null) {
                for (NetworkInterface ni : Collections.list(ifaces)) {
                    if (ni.isLoopback() || !ni.isUp()) continue;
                    String name = ni.getName() == null ? "" : ni.getName().toLowerCase();
                    if (!(name.startsWith("wlan") || name.startsWith("ap") || name.startsWith("eth"))) continue;
                    for (InetAddress a : Collections.list(ni.getInetAddresses())) {
                        if (a instanceof Inet4Address && !a.isLoopbackAddress()) {
                            return a.getHostAddress();
                        }
                    }
                }
            }
        } catch (Throwable t) {
            Log.w(TAG, "NetworkInterface failed", t);
        }
        return null;
    }

    private void startScan() {
        final String localIp = localWifiIpv4();
        if (localIp == null) {
            setStatus("拿不到手机 Wi-Fi 的 IP，请确认已连上 Wi-Fi，或手动填地址。");
            toast("请先连接 Wi-Fi");
            return;
        }
        int lastDot = localIp.lastIndexOf('.');
        if (lastDot <= 0) {
            setStatus("Wi-Fi 地址异常：" + localIp + "，请手动填地址。");
            return;
        }
        final String prefix = localIp.substring(0, lastDot + 1);
        final String self = localIp;

        scanning = true;
        cancelled.set(false);
        scanBtn.setText("取消扫描");
        progress.setVisibility(View.VISIBLE);
        progress.setProgress(0);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        setStatus("正在扫描 " + prefix + "1-254（本机 " + self + "）…");

        final AtomicInteger done = new AtomicInteger(0);
        final AtomicInteger foundCount = new AtomicInteger(0);
        scanPool = Executors.newFixedThreadPool(SCAN_THREADS);
        final List<String> hosts = new ArrayList<String>();
        for (int i = 1; i <= 254; i++) {
            hosts.add(prefix + i);
        }
        for (final String ip : hosts) {
            scanPool.execute(new Runnable() {
                @Override
                public void run() {
                    if (cancelled.get()) return;
                    boolean hit = probe(ip);
                    if (hit && foundCount.incrementAndGet() == 1 && !cancelled.get()) {
                        ui.post(new Runnable() {
                            @Override
                            public void run() {
                                if (cancelled.get()) return;
                                hostInput.setText(ip + ":" + DEFAULT_PORT);
                                setStatus("已找到电脑：" + ip + ":" + DEFAULT_PORT + "，点「保存并连接」进入。");
                                toast("已找到电脑");
                                cancelScan();
                            }
                        });
                        return;
                    }
                    int d = done.incrementAndGet();
                    if (d % 8 == 0 || d == hosts.size()) {
                        ui.post(new Runnable() {
                            @Override
                            public void run() {
                                if (scanning) progress.setProgress(done.get());
                            }
                        });
                    }
                }
            });
        }
        // 收尾：全部扫完仍没找到就给出提示
        scanPool.shutdown();
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    scanPool.awaitTermination(60, TimeUnit.SECONDS);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
                ui.post(new Runnable() {
                    @Override
                    public void run() {
                        if (!scanning || cancelled.get()) return;
                        if (foundCount.get() == 0) {
                            setStatus("没找到，请确认手机和电脑在同一个 Wi-Fi，或手动填地址。");
                        }
                        finishScanUi();
                    }
                });
            }
        }).start();
    }

    private void cancelScan() {
        cancelled.set(true);
        finishScanUi();
        if (scanning) {
            setStatus("已取消扫描。");
        }
    }

    private void finishScanUi() {
        scanning = false;
        scanBtn.setText("扫描局域网");
        progress.setVisibility(View.GONE);
        getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        stopPool();
    }

    private void stopPool() {
        ExecutorService p = scanPool;
        scanPool = null;
        if (p != null) {
            try {
                p.shutdownNow();
            } catch (Throwable ignored) {
            }
        }
    }

    /**
     * 探测单个 IP 是否是控制台。
     * 指纹接口：GET http://ip:8787/api/login 返回 200 且响应体含 "ok"（无需鉴权）。
     */
    private boolean probe(String ip) {
        HttpURLConnection conn = null;
        InputStream in = null;
        try {
            URL url = new URL("http://" + ip + ":" + DEFAULT_PORT + "/api/login");
            conn = (HttpURLConnection) url.openConnection();
            conn.setConnectTimeout(SCAN_TIMEOUT_MS);
            conn.setReadTimeout(SCAN_TIMEOUT_MS);
            conn.setRequestMethod("GET");
            conn.setUseCaches(false);
            conn.setRequestProperty("Connection", "close");
            conn.setRequestProperty("Accept", "*/*");
            int code = conn.getResponseCode();
            if (code != 200) return false;
            in = conn.getInputStream();
            byte[] buf = new byte[512];
            int n = in.read(buf);
            if (n <= 0) return false;
            String body = new String(buf, 0, n, "UTF-8");
            return body.contains("ok");
        } catch (Throwable t) {
            return false;
        } finally {
            try {
                if (in != null) in.close();
            } catch (Throwable ignored) {
            }
            if (conn != null) conn.disconnect();
        }
    }

    @Override
    public void onBackPressed() {
        if (scanning) {
            cancelScan();
            return;
        }
        super.onBackPressed();
    }
}
