# -*- coding: utf-8 -*-
"""v2.6 手机端打磨：
1) 修 MainActivity 编译错误（static 里用 getApplicationContext）
2) 扫码预览不再拉伸（按实际预览旋转方向算比例 + 居中裁切填满）
3) 登录/连接页整体重做：深色高级感 UI + 自动扫描 + 剪贴板提示 + 折叠帮助
"""
import io
import os
import re

SRC = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console\android-app\app\src\main\java\com\home\phoneconsole'
MAIN = os.path.join(SRC, 'MainActivity.java')
SCAN = os.path.join(SRC, 'ScannerActivity.java')
SETUP = os.path.join(SRC, 'SetupActivity.java')


def read(p):
    return io.open(p, encoding='utf-8').read()


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


# ============================================================ 1) MainActivity 编译错误
main = read(MAIN)
main = main.replace("        installCrashLogger();", "        installCrashLogger(this);")
main = main.replace("    private static void installCrashLogger() {",
                    "    private static void installCrashLogger(final android.content.Context appCtx) {")
main = main.replace('java.io.File f = new java.io.File(getApplicationContext().getFilesDir(), "last-crash.txt");',
                    'java.io.File f = new java.io.File(appCtx.getFilesDir(), "last-crash.txt");')
write(MAIN, main)
print('MainActivity: 编译错误已修')

# ============================================================ 2) 扫码预览比例
scan = read(SCAN)

# 2.1 记录实际应用的预览旋转角
scan = scan.replace("    private Camera.Size previewSize;",
                    "    private Camera.Size previewSize;\n    private int appliedDisplayOrientation = 0;   // 实际给相机设置的旋转角（0/90/180/270）")

if "appliedDisplayOrientation = result;" not in scan:
    scan = scan.replace("            camera.setDisplayOrientation(result);",
                        "            appliedDisplayOrientation = result;\n            camera.setDisplayOrientation(result);")

# 2.2 swap 依据"实际旋转角"而不是屏幕旋转（手机竖持时屏幕旋转是 0，但预览要转 90°）
old_swap = """    /** 竖屏时预览画面要按 90° 旋转处理 */
    private boolean isPortraitSwap() {
        int rot = displayRotationDegrees();
        return rot == 90 || rot == 270;
    }"""
new_swap = """    /** 预览画面是否需要交换长宽：由"实际给相机的旋转角"决定。
        之前用屏幕旋转判断：手机竖持时 screen rotation=0 但预览必须转 90°，
        于是 SurfaceView 被按横向比例摆放，画面被硬拉成横的（真机踩过）。 */
    private boolean isPortraitSwap() {
        if (appliedDisplayOrientation % 180 == 90) return true;
        int rot = displayRotationDegrees();
        return rot == 90 || rot == 270;
    }"""
assert old_swap in scan, 'isPortraitSwap anchor missing'
scan = scan.replace(old_swap, new_swap)

# 2.3 居中裁切填满（scale 用 max，保持比例不变形、只裁边）
old_layout = """            int[] wh = screenSize();
            float scale = Math.min(wh[0] / dispW, wh[1] / dispH);
            int w = Math.round(dispW * scale);
            int h = Math.round(dispH * scale);"""
new_layout = """            int[] wh = screenSize();
            // 取 max：画面按比例放大到铺满屏幕，多出来的部分被裁掉（扫描器的最佳观感），
            // 用 min 会留黑边、而且某些机器上 SurfaceView 会被再拉伸一次。
            float scale = Math.max(wh[0] / dispW, wh[1] / dispH);
            int w = Math.round(dispW * scale);
            int h = Math.round(dispH * scale);"""
assert old_layout in scan, 'layout anchor missing'
scan = scan.replace(old_layout, new_layout)
write(SCAN, scan)
print('ScannerActivity: 预览比例已修（按实际旋转角 + 居中裁切）')

# ============================================================ 3) 登录/连接页重做
setup = read(SETUP)

start_marker = "        final boolean firstRun = !Prefs.isConfigured(this);"
end_marker = """        if (firstRun) {
            statusText.setText("还没设置地址。点「扫描局域网」或手动填写。");
        } else {
            statusText.setText("当前地址：" + Prefs.getHost(this));
        }
"""
s_idx = setup.index(start_marker)
e_idx = setup.index(end_marker) + len(end_marker)

ui = r'''        final boolean firstRun = !Prefs.isConfigured(this);

        applyDarkSystemBars();

        ScrollView scroll = new ScrollView(this);
        scroll.setBackground(darkBackdrop());
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
        title.setTextColor(Color.parseColor("#EEF3FA"));
        title.setGravity(Gravity.CENTER);
        title.setPadding(0, dp(14), 0, 0);
        root.addView(title);

        TextView sub = new TextView(this);
        sub.setText("在手机上远程操作电脑里的 DSH 智能体");
        sub.setTextSize(12.5f);
        sub.setTextColor(Color.parseColor("#7B869B"));
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
        card.setBackground(roundBg("#111721", 20, "#1E2735", 1));
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

        // 粘贴（文字按钮）
        TextView paste = new TextView(this);
        paste.setText("从剪贴板粘贴");
        paste.setTextSize(13f);
        paste.setTextColor(Color.parseColor("#61E2AC"));
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
        statusText.setTextColor(Color.parseColor("#9AA6BA"));
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
        helpTitle.setTextColor(Color.parseColor("#7B869B"));
        helpTitle.setPadding(0, dp(20), 0, dp(8));
        root.addView(helpTitle);

        final TextView help = new TextView(this);
        help.setTextSize(12f);
        help.setTextColor(Color.parseColor("#6B7688"));
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
        verText.setTextColor(Color.parseColor("#4E5868"));
        verText.setGravity(Gravity.CENTER);
        verText.setPadding(0, dp(24), 0, dp(6));
        root.addView(verText);

        setContentView(scroll);

        refreshHistory();
        if (firstRun) {
            setStatus("还没有地址：可以「扫码连接」或用「扫描局域网」自动发现");
        } else {
            setStatus("当前地址：" + Prefs.getHost(this));
        }
'''
setup = setup[:s_idx] + ui + setup[e_idx:]

# 3.1 外观辅助整体换成深色高级版
helpers_start = setup.index("    /** 输入框统一外观：白底 + 浅描边 + 圆角 12dp */")
helpers_end = setup.index("    private void toast(String msg) {")
new_helpers = r'''    /** 深色渐变底：顶部 #0E141C → 底部 #070A0E */
    private android.graphics.drawable.Drawable darkBackdrop() {
        android.graphics.drawable.GradientDrawable d = new android.graphics.drawable.GradientDrawable(
                android.graphics.drawable.GradientDrawable.Orientation.TOP_BOTTOM,
                new int[]{Color.parseColor("#0E141C"), Color.parseColor("#070A0E")});
        return d;
    }

    /** 状态栏/导航栏切成深色（浅色图标） */
    private void applyDarkSystemBars() {
        try {
            getWindow().setStatusBarColor(Color.parseColor("#0A0E13"));
            getWindow().setNavigationBarColor(Color.parseColor("#070A0E"));
            if (Build.VERSION.SDK_INT >= 23) {
                getWindow().getDecorView().setSystemUiVisibility(0);   // 不要浅色图标
            }
        } catch (Throwable ignored) {
        }
    }

    /** 分组小标题：大写感 + 字距 */
    private TextView sectionLabel(String text) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTextSize(11f);
        tv.setTextColor(Color.parseColor("#66748A"));
        tv.setPadding(0, dp(14), 0, dp(6));
        if (Build.VERSION.SDK_INT >= 21) tv.setLetterSpacing(0.06f);
        return tv;
    }

    /** 输入框：深色底 + 发丝描边 + 聚焦薄荷描边 */
    private void styleInput(final EditText e) {
        e.setTextSize(15f);
        e.setTextColor(Color.parseColor("#E8EEF7"));
        e.setHintTextColor(Color.parseColor("#4E5868"));
        final android.graphics.drawable.Drawable normal = roundBg("#0B1119", 13, "#232D3C", 1);
        final android.graphics.drawable.Drawable focus = roundBg("#0B1119", 13, "#3FDC95", 1);
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
        b.setTextColor(Color.parseColor("#06130D"));
        android.graphics.drawable.GradientDrawable g = new android.graphics.drawable.GradientDrawable(
                android.graphics.drawable.GradientDrawable.Orientation.LEFT_RIGHT,
                new int[]{Color.parseColor("#56ECAE"), Color.parseColor("#22B877")});
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
        b.setTextColor(Color.parseColor("#CFE8DC"));
        b.setBackground(rippleBg("#131B25", 12, "#27313F", 1));
        b.setPadding(dp(6), dp(10), dp(6), dp(10));
    }

    private TextView label(String text) {
        return sectionLabel(text);
    }

'''
setup = setup[:helpers_start] + new_helpers + setup[helpers_end:]

# 3.2 setStatus 深色化 + 历史地址 chip 深色化
setup = setup.replace("""    private void setStatus(String msg) {
        statusText.setText(msg);
        // 空内容就整块隐藏（首屏不该出现一个没有任何文字的白框）
        statusText.setVisibility((msg == null || msg.length() == 0) ? View.GONE : View.VISIBLE);
    }""", """    private void setStatus(String msg) {
        statusText.setText(msg);
        // 空内容就整块隐藏（首屏不该出现一个没有任何文字的空白块）
        statusText.setVisibility((msg == null || msg.length() == 0) ? View.GONE : View.VISIBLE);
    }""")

old_hist = setup[setup.index("    private void refreshHistory() {"):setup.index("    // ------------------------------------------------------------------\n    // 地址解析与保存")]
new_hist = r'''    private void refreshHistory() {
        if (historyBox == null) return;
        historyBox.removeAllViews();
        List<String> hist = Prefs.getHistory(this);
        if (hist.isEmpty()) {
            TextView empty = new TextView(this);
            empty.setText("暂无历史地址");
            empty.setTextSize(12f);
            empty.setTextColor(Color.parseColor("#4E5868"));
            empty.setPadding(dp(2), dp(8), 0, dp(4));
            historyBox.addView(empty);
            return;
        }
        TextView cap = new TextView(this);
        cap.setText("最近使用");
        cap.setTextSize(11f);
        cap.setTextColor(Color.parseColor("#66748A"));
        cap.setPadding(dp(2), 0, 0, dp(8));
        historyBox.addView(cap);

        for (final String h : hist) {
            TextView b = new TextView(this);
            b.setText(h);
            b.setTextSize(13f);
            b.setTextColor(Color.parseColor("#C6D2E2"));
            b.setGravity(Gravity.CENTER_VERTICAL);
            b.setBackground(rippleBg("#121924", 12, "#222B39", 1));
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

'''
setup = setup.replace(old_hist, new_hist)

# 3.3 首屏优化：自动扫描局域网 + 剪贴板里有地址就提示
setup = setup.replace("""        refreshHistory();
        if (firstRun) {
            setStatus("还没有地址：可以「扫码连接」或用「扫描局域网」自动发现");
        } else {
            setStatus("当前地址：" + Prefs.getHost(this));
        }""", """        refreshHistory();
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
        }""")

# 3.4 提供 clipboardText()（pasteFromClipboard 内部有类似逻辑）
if "private String clipboardText()" not in setup:
    setup = setup.replace("    private void pasteFromClipboard() {", """    private String clipboardText() {
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

    private void pasteFromClipboard() {""", 1)
write(SETUP, setup)
print('SetupActivity: 深色高级 UI + 自动扫描 + 折叠帮助')
