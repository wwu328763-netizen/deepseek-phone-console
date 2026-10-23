# -*- coding: utf-8 -*-
"""v3.0.4：手机端打磨 6 项
1 长按可复制（去掉拦截长按的原生菜单，保留文字选择）
2 扫码后自动登录（WebView 暴露 PhoneConsole.pin()，网页登录页自动提交）
3 选文件返回后 WebView 恢复焦点
4 双击返回直接回桌面（finishAffinity，不再停在空白 Activity）
5 进入聊天前显示原生加载遮罩（图标 + 正在连接…），消灭长空白
6 图标去掉自适应层，直接用旧版 PNG（部分启动器缓存/主题图标会显示成别的样子）
"""
import io
import os
import shutil

PHONE = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console'
SRC = os.path.join(PHONE, 'android-app', 'app', 'src', 'main', 'java', 'com', 'home', 'phoneconsole')
RES = os.path.join(PHONE, 'android-app', 'app', 'src', 'main', 'res')


def read(p):
    return io.open(p, encoding='utf-8').read()


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


pa = os.path.join(SRC, 'MainActivity.java')
m = read(pa)

# ---------- 1) 长按：不再弹原生菜单，交给系统文字选择（可复制） ----------
old_long = '''        // 长按 WebView 也能叫出菜单（顶栏 ⋮ 之外的第二入口）
        web.setOnLongClickListener(new View.OnLongClickListener() {
            @Override
            public boolean onLongClick(View v) {
                showMenu();
                return true;
            }
        });'''
new_long = '''        // 长按不再拦成原生菜单：要让系统文字选择（复制/全选/分享）工作。
        // 旧菜单改成「长按标题」再叫出来（见下方 appIcon 长按），不影响正文复制。
        web.setLongClickable(true);
        web.setHapticFeedbackEnabled(false);'''
if old_long in m:
    m = m.replace(old_long, new_long, 1)

# ---------- 4) 双击返回 → 直接回桌面 ----------
m = m.replace('''            if (now - lastBackTime < 2000) {
                finish();
            } else {''', '''            if (now - lastBackTime < 2000) {
                // finish() 只结束 MainActivity，任务里可能还留着空壳 → 先看到"空白界面"。
                // finishAffinity 把整个任务清掉，直接回桌面。
                finishAffinity();
            } else {''')

# ---------- 5) 原生加载遮罩 ----------
if 'loadingView' not in m:
    m = m.replace('''    private ValueCallback<Uri[]> filePathCallback;''', '''    private ValueCallback<Uri[]> filePathCallback;
    /** 进入聊天前的原生加载遮罩（避免隧道慢时长时间空白） */
    private View loadingView;''')

    # 构造遮罩（放在 content 里，盖在 WebView 上）
    m = m.replace('''        setContentView(content);''', '''        loadingView = buildLoadingView();
        content.addView(loadingView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        setContentView(content);''')

    # 构造方法
    m = m.replace('''    /** 内容淡入（页面加载完成后调用，避免硬切） */''', '''    /** 原生加载遮罩：图标 + 旋转圈 + 文案（隧道慢/首屏白屏时给反馈） */
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

    /** 内容淡入（页面加载完成后调用，避免硬切） */''')

    # 加载时显示、完成/失败时隐藏
    m = m.replace('''    private void loadConsole() {
        errorView = null;
        loadFailed = false;''', '''    private void loadConsole() {
        errorView = null;
        loadFailed = false;
        if (loadingView != null) loadingView.setVisibility(View.VISIBLE);''')
    m = m.replace('''            bar.setVisibility(View.GONE);
            bar.setProgress(0);
            fadeInWeb();''', '''            bar.setVisibility(View.GONE);
            bar.setProgress(0);
            if (loadingView != null) loadingView.setVisibility(View.GONE);
            fadeInWeb();''')
    m = m.replace('''        web.loadDataWithBaseURL(null, html, "text/html", "UTF-8", null);
        web.setVisibility(View.VISIBLE);''', '''        if (loadingView != null) loadingView.setVisibility(View.GONE);
        web.loadDataWithBaseURL(null, html, "text/html", "UTF-8", null);
        web.setVisibility(View.VISIBLE);''')

# ---------- 3) 选文件返回后恢复 WebView 焦点 ----------
m = m.replace('''            if (filePathCallback != null) {
                filePathCallback.onReceiveValue(results);
                filePathCallback = null;
            }
            return;''', '''            if (filePathCallback != null) {
                filePathCallback.onReceiveValue(results);
                filePathCallback = null;
            }
            // 返回聊天界面后有些机型会失去焦点 → 整个 WebView 像死掉一样点不动
            try {
                web.setFocusable(true);
                web.requestFocus();
            } catch (Throwable ignored) {
            }
            return;''')

# ---------- 2) 桥接：暴露 PIN 给网页自动登录 ----------
m = m.replace('''    /** 错误页按钮回调 */
    private class PageBridge {''', '''    /** 错误页按钮回调 */
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
        }''')
write(pa, m)
print('MainActivity: 长按复制 / 双击回桌面 / 加载遮罩 / 选文件焦点 / pin 桥')

# ---------- 2b) Web：登录页用 PhoneConsole.pin() 自动登录 ----------
APP = os.path.join(PHONE, 'webapp', 'src', 'app.tsx')
a = read(APP)
if 'PhoneConsole.pin' not in a:
    old_login = """  useEffect(() => {
    const q = new URLSearchParams(location.search).get('pin');
    const pin = q || getPin();
    if (pin) { login(pin).catch(() => setPinReady(true)); }
    else setPinReady(true);
  }, []);"""
    new_login = """  useEffect(() => {
    const q = new URLSearchParams(location.search).get('pin');
    // APK 壳里还带着「扫码/上次保存的 PIN」，即使 URL 没带也能自动登录
    let nativePin = '';
    try {
      const app = (window as any).PhoneConsole;
      if (app && typeof app.pin === 'function') nativePin = String(app.pin() || '');
    } catch (e) { nativePin = ''; }
    const pin = q || getPin() || nativePin;
    if (pin) { login(pin).catch(() => setPinReady(true)); }
    else setPinReady(true);
  }, []);"""
    assert old_login in a, 'login bootstrap anchor missing'
    a = a.replace(old_login, new_login, 1)
    write(APP, a)
    print('app.tsx: 登录页自动用原生桥的 PIN')

# ---------- 6) 图标：删掉自适应层，直接用旧版 PNG ----------
anydpi = os.path.join(RES, 'mipmap-anydpi-v26')
if os.path.isdir(anydpi):
    shutil.rmtree(anydpi)
    print('res: 已删除 mipmap-anydpi-v26（改用旧版 PNG 图标）')
# roundIcon 也回退成同一张，避免个别启动器拿自适应图标
mm = os.path.join(PHONE, 'android-app', 'app', 'src', 'main', 'AndroidManifest.xml')
mmx = read(mm)
mmx = mmx.replace('        android:roundIcon="@mipmap/ic_launcher_round"\n', '')
write(mm, mmx)
print('manifest: 去掉 roundIcon 自适应回退')
