# -*- coding: utf-8 -*-
"""v3.0.0 大批量：
1 图标回旧版（电脑端旧界面那枚）
2 登录页改黑白 + DeepSeek 蓝，和对话页统一
3 修 /api/sessions/{id}/send 404
4 上传加超时保护（不再无限卡）
5 v2 设置加「充值」入口
6 APK 增加「启动时显示登录页」开关（Prefs）
7 过渡动画：Activity 淡入 + WebView 内容淡入
9 版本号从 3.0.0 起
"""
import io
import os
import shutil

PHONE = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console'
SRC = os.path.join(PHONE, 'android-app', 'app', 'src', 'main', 'java', 'com', 'home', 'phoneconsole')
KSRC = os.path.join(PHONE, 'android-app', 'app', 'src', 'main', 'kotlin', 'com', 'home', 'phoneconsole')


def read(p):
    return io.open(p, encoding='utf-8').read()


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


# ============================================================ 3) 服务端：sessions send 别名
srv = os.path.join(PHONE, 'server.py')
s = read(srv)
if 'action == "send"' not in s:
    s = s.replace('''            if action == "continue":
                data = self._read_json()''', '''            if action == "send":
                # v2 手机界面统一调 /api/{kind}/{id}/send；sessions 旧契约叫 continue。
                # 之前只有 continue，补上 send 别名，否则手机发消息就是 HTTP 404。
                action = "continue"
            if action == "continue":
                data = self._read_json()''')
    write(srv, s)
    print('server: /api/sessions/{id}/send 别名已加')

# ============================================================ 6) Prefs：显示登录页开关
prefs = os.path.join(KSRC, 'Prefs.kt')
p = read(prefs)
if 'KEY_REQUIRE_LOGIN' not in p:
    p = p.replace('    private const val KEY_HISTORY = "history"',
                  '    private const val KEY_HISTORY = "history"\n    private const val KEY_REQUIRE_LOGIN = "require_login"')
    p = p.replace('''    @JvmStatic
    fun clearAll(ctx: Context) {''', '''    /** 启动时是否强制显示网页登录页（URL 不带 PIN）。默认 false：连过就直接进。 */
    @JvmStatic
    fun getRequireLogin(ctx: Context): Boolean = sp(ctx).getBoolean(KEY_REQUIRE_LOGIN, false)

    @JvmStatic
    fun setRequireLogin(ctx: Context, on: Boolean) {
        edit(ctx) { putBoolean(KEY_REQUIRE_LOGIN, on) }
    }

    @JvmStatic
    fun clearAll(ctx: Context) {''')
    write(prefs, p)
    print('Prefs: requireLogin 开关已加')

# ============================================================ 6+7) MainActivity：登录页开关 + 过渡动画
main_p = os.path.join(SRC, 'MainActivity.java')
m = read(main_p)

# 6.1 URL 组装时按开关决定是否带 PIN
if 'Prefs.getRequireLogin' not in m:
    m = m.replace('''    private String consoleUrl() {
        return SetupActivity.buildUrl(Prefs.getHost(this), Prefs.getPin(this));
    }''', '''    private String consoleUrl() {
        // 「启动时显示登录页」打开时不把 PIN 放进 URL，网页会先要 PIN
        String pin = Prefs.getRequireLogin(this) ? "" : Prefs.getPin(this);
        return SetupActivity.buildUrl(Prefs.getHost(this), pin);
    }''')

# 7.1 Activity 过渡动画：进入 WebView 后淡入；页面加载完成再淡入内容
if 'overridePendingTransition' not in m:
    m = m.replace('''        setupWebView();
        loadConsole();
    }''', '''        setupWebView();
        loadConsole();

        // 过渡：从连接页进来时整体淡入，WebView 内容 0.22s 渐显（避免白屏硬切）
        try {
            web.setAlpha(0f);
            web.animate().alpha(1f).setDuration(240).start();
        } catch (Throwable ignored) {
        }
    }''')
    m = m.replace('''    @Override
    protected void onResume() {
        super.onResume();''', '''    @Override
    public void onAttachedToWindow() {
        super.onAttachedToWindow();
    }

    @Override
    protected void onResume() {
        super.onResume();''')

# 7.2 页面 finished 时再补一次淡入（错误页也适用）
if 'fadeInWeb' not in m:
    m = m.replace('''        @Override
        public void onPageFinished(WebView view, String url) {
            bar.setVisibility(View.GONE);
            bar.setProgress(0);
        }''', '''        @Override
        public void onPageFinished(WebView view, String url) {
            bar.setVisibility(View.GONE);
            bar.setProgress(0);
            fadeInWeb();
        }''')
    m = m.replace('''    /** 出错时给出可操作的错误页，而不是白屏 */''', '''    /** 内容淡入（页面加载完成后调用，避免硬切） */
    private void fadeInWeb() {
        try {
            if (web != null && web.getAlpha() < 1f) {
                web.animate().alpha(1f).setDuration(220).start();
            }
        } catch (Throwable ignored) {
        }
    }

    /** 出错时给出可操作的错误页，而不是白屏 */''')
write(main_p, m)
print('MainActivity: 登录页开关 + 淡入过渡')

# ============================================================ 2) 登录页：白底 + 黑 + DeepSeek 蓝
setup_p = os.path.join(SRC, 'SetupActivity.java')
su = read(setup_p)

su = su.replace('private android.graphics.drawable.Drawable darkBackdrop() {',
                'private android.graphics.drawable.Drawable pageBackdrop() {')
su = su.replace('''        android.graphics.drawable.GradientDrawable d = new android.graphics.drawable.GradientDrawable(
                android.graphics.drawable.GradientDrawable.Orientation.TOP_BOTTOM,
                new int[]{Color.parseColor("#0E141C"), Color.parseColor("#070A0E")});
        return d;''', '''        // 白 → 极浅灰，和对话页（白底黑字）一致
        android.graphics.drawable.GradientDrawable d = new android.graphics.drawable.GradientDrawable(
                android.graphics.drawable.GradientDrawable.Orientation.TOP_BOTTOM,
                new int[]{Color.parseColor("#FFFFFF"), Color.parseColor("#F4F6FB")});
        return d;''')
su = su.replace('scroll.setBackground(darkBackdrop());', 'scroll.setBackground(pageBackdrop());')

# 2.1 系统栏：白底黑字
su = su.replace('''            getWindow().setStatusBarColor(Color.parseColor("#0A0E13"));
            getWindow().setNavigationBarColor(Color.parseColor("#070A0E"));
            if (Build.VERSION.SDK_INT >= 23) {
                getWindow().getDecorView().setSystemUiVisibility(0);   // 不要浅色图标
            }''', '''            getWindow().setStatusBarColor(Color.WHITE);
            getWindow().setNavigationBarColor(Color.WHITE);
            if (Build.VERSION.SDK_INT >= 23) {
                // 白底浅色状态栏 → 用深色图标
                getWindow().getDecorView().setSystemUiVisibility(
                        android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
            }''')

# 2.2 文字/卡片颜色：黑字白卡 + DeepSeek 蓝
su = su.replace('title.setTextColor(Color.parseColor("#EEF3FA"));', 'title.setTextColor(Color.parseColor("#0D0D0F"));')
su = su.replace('sub.setTextColor(Color.parseColor("#7B869B"));', 'sub.setTextColor(Color.parseColor("#6B7280"));')
su = su.replace('card.setBackground(roundBg("#111721", 20, "#1E2735", 1));', 'card.setBackground(roundBg("#FFFFFF", 20, "#EAECF2", 1));')
su = su.replace('tv.setTextColor(Color.parseColor("#66748A"));', 'tv.setTextColor(Color.parseColor("#8A8F9C"));')
su = su.replace('e.setTextColor(Color.parseColor("#E8EEF7"));', 'e.setTextColor(Color.parseColor("#0D0D0F"));')
su = su.replace('e.setHintTextColor(Color.parseColor("#4E5868"));', 'e.setHintTextColor(Color.parseColor("#A6ABB8"));')
su = su.replace('final android.graphics.drawable.Drawable normal = roundBg("#0B1119", 13, "#232D3C", 1);',
                'final android.graphics.drawable.Drawable normal = roundBg("#FFFFFF", 13, "#E5E8EF", 1);')
su = su.replace('final android.graphics.drawable.Drawable focus = roundBg("#0B1119", 13, "#3FDC95", 1);',
                'final android.graphics.drawable.Drawable focus = roundBg("#FFFFFF", 13, "#4D6BFE", 1);')
su = su.replace('b.setTextColor(Color.parseColor("#06130D"));', 'b.setTextColor(Color.WHITE);')
su = su.replace('new int[]{Color.parseColor("#56ECAE"), Color.parseColor("#22B877")});',
                'new int[]{Color.parseColor("#5B7BFF"), Color.parseColor("#4D6BFE")});')
su = su.replace('b.setTextColor(Color.parseColor("#CFE8DC"));', 'b.setTextColor(Color.parseColor("#0D0D0F"));')
su = su.replace('b.setBackground(rippleBg("#131B25", 12, "#27313F", 1));',
                'b.setBackground(rippleBg("#FFFFFF", 12, "#E5E8EF", 1));')
su = su.replace('paste.setTextColor(Color.parseColor("#61E2AC"));', 'paste.setTextColor(Color.parseColor("#4D6BFE"));')
su = su.replace('statusText.setTextColor(Color.parseColor("#9AA6BA"));', 'statusText.setTextColor(Color.parseColor("#6B7280"));')
su = su.replace('verText.setTextColor(Color.parseColor("#4E5868"));', 'verText.setTextColor(Color.parseColor("#B4B8C2"));')
su = su.replace('helpTitle.setTextColor(Color.parseColor("#7B869B"));', 'helpTitle.setTextColor(Color.parseColor("#6B7280"));')
su = su.replace('help.setTextColor(Color.parseColor("#6B7688"));', 'help.setTextColor(Color.parseColor("#8A8F9C"));')
su = su.replace('b.setTextColor(Color.parseColor("#C6D2E2"));', 'b.setTextColor(Color.parseColor("#0D0D0F"));')
su = su.replace('b.setBackground(rippleBg("#121924", 12, "#222B39", 1));',
                'b.setBackground(rippleBg("#F7F8FB", 12, "#EAECF2", 1));')
su = su.replace('cap.setTextColor(Color.parseColor("#66748A"));', 'cap.setTextColor(Color.parseColor("#8A8F9C"));')
su = su.replace('empty.setTextColor(Color.parseColor("#4E5868"));', 'empty.setTextColor(Color.parseColor("#A6ABB8"));')

# 2.3 加「启动时显示登录页」开关（放在连接卡片底部、粘贴之上）
if 'requireLoginCb' not in su:
    su = su.replace('''        // 粘贴（文字按钮）''', '''        // 启动时是否先显示网页登录页
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

        // 粘贴（文字按钮）''')
write(setup_p, su)
print('SetupActivity: 黑白 + DeepSeek 蓝 + 登录页开关')

# ============================================================ 4) 上传超时保护（v2）
api_ts = os.path.join(PHONE, 'webapp', 'src', 'api.ts')
a = read(api_ts)
if 'UPLOAD_TIMEOUT_MS' not in a:
    a = a.replace('export function uploadWithProgress(', '''/* 上传兜底：60 秒没结果就失败，避免界面"卡死"（大文件走隧道时服务器/网络可能不回应） */
export const UPLOAD_TIMEOUT_MS = 60000;

export function uploadWithProgress(''')
    a = a.replace("      xhr.open('POST', `/api/${kind === 'thread' ? 'threads' : 'sessions'}/${id}/upload`, true);",
                  "      xhr.open('POST', `/api/${kind === 'thread' ? 'threads' : 'sessions'}/${id}/upload`, true);\n      xhr.timeout = UPLOAD_TIMEOUT_MS;\n      xhr.ontimeout = () => reject(new Error('上传超时（60s），请检查网络或换小一点的文件'));")
    write(api_ts, a)
    print('api.ts: 上传超时保护')

print('DONE part 1')
