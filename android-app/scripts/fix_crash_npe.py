# -*- coding: utf-8 -*-
"""修 APK 启动闪退：MainActivity 删了原生顶栏却仍在 loadConsole() 里 titleView.setText() → NPE。
   同时加崩溃日志落盘（files/last-crash.txt）并在 SetupActivity 显示上次崩溃摘要。"""
import io
import os

SRC = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console\android-app\app\src\main\java\com\home\phoneconsole'
MAIN = os.path.join(SRC, 'MainActivity.java')
SETUP = os.path.join(SRC, 'SetupActivity.java')


def read(p):
    return io.open(p, encoding='utf-8').read()


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


main = read(MAIN)

# 1) 去掉对已删除顶栏的引用（这就是闪退原因）
old = """        String url = consoleUrl();
        titleView.setText(Prefs.getHost(this));
        web.setVisibility(View.VISIBLE);"""
new = """        String url = consoleUrl();
        // 原生顶栏已移除：titleView 永远是 null，之前这里直接 NPE → 启动瞬间闪退
        if (titleView != null) titleView.setText(Prefs.getHost(this));
        web.setVisibility(View.VISIBLE);"""
assert old in main, 'loadConsole anchor missing'
main = main.replace(old, new)

# 2) 崩溃写文件（便于以后定位；不改动原有行为，仍交给系统默认处理器）
anchor = "        applyLightSystemBars();"
crash = """        installCrashLogger();

        applyLightSystemBars();"""
assert anchor in main
main = main.replace(anchor, crash, 1)

helper_anchor = "    private String consoleUrl() {"
helper = """    /** 启动期崩溃落盘到 files/last-crash.txt，方便用户把原因发回来 */
    private static void installCrashLogger() {
        try {
            if (sCrashLoggerInstalled) return;
            sCrashLoggerInstalled = true;
            final Thread.UncaughtExceptionHandler def = Thread.getDefaultUncaughtExceptionHandler();
            Thread.setDefaultUncaughtExceptionHandler(new Thread.UncaughtExceptionHandler() {
                @Override
                public void uncaughtException(Thread t, Throwable e) {
                    try {
                        java.io.File f = new java.io.File(getApplicationContext().getFilesDir(), "last-crash.txt");
                        java.io.FileOutputStream fo = new java.io.FileOutputStream(f);
                        fo.write(("time=" + new java.util.Date() + "\\n" + Log.getStackTraceString(e)).getBytes("UTF-8"));
                        fo.close();
                    } catch (Throwable ignored) {
                    }
                    if (def != null) def.uncaughtException(t, e);
                }
            });
        } catch (Throwable ignored) {
        }
    }

    private String consoleUrl() {"""
assert helper_anchor in main
main = main.replace(helper_anchor, helper, 1)

# 静态标记
main = main.replace("    private long lastBackTime = 0L;",
                    "    private static boolean sCrashLoggerInstalled = false;\n    private long lastBackTime = 0L;")
write(MAIN, main)
print('MainActivity: NPE 已修 + 崩溃日志')

# 3) SetupActivity：显示上次崩溃摘要（若有）
setup = read(SETUP)
anchor2 = """        root.addView(sub);"""
hint = """        root.addView(sub);

        // 上次启动崩溃摘要（只读，便于反馈问题）
        try {
            java.io.File cf = new java.io.File(getFilesDir(), "last-crash.txt");
            if (cf.exists()) {
                String txt = readTextFile(cf);
                if (txt != null && txt.length() > 0) {
                    TextView crash = new TextView(this);
                    crash.setTextSize(11.5f);
                    crash.setTextColor(Color.parseColor("#C0392B"));
                    crash.setBackgroundColor(Color.parseColor("#FFF1F0"));
                    crash.setPadding(dp(12), dp(10), dp(12), dp(10));
                    crash.setText("上次启动出错（可截图反馈）：\\n" + txt);
                    LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(
                            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
                    clp.bottomMargin = dp(14);
                    root.addView(crash, clp);
                }
            }
        } catch (Throwable ignored) {
        }"""
assert anchor2 in setup
setup = setup.replace(anchor2, hint, 1)

# 简单读文件辅助（不引额外 import）
helper2 = """    private static String readTextFile(java.io.File f) {
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

    private void saveAndConnect() {"""
assert "    private void saveAndConnect() {" in setup
setup = setup.replace("    private void saveAndConnect() {", helper2, 1)
write(SETUP, setup)
print('SetupActivity: 崩溃摘要展示')
