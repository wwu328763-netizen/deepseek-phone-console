package com.home.phoneconsole;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.util.Log;
import android.widget.Toast;

import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 「检查更新」：从 &lt;控制台地址&gt;/app-version.json 拉版本信息，
 * versionCode 比本机大时下载 APK 到 getCacheDir()，用 FileProvider 生成 content://
 * Uri 并通过 ACTION_VIEW 交给系统安装器。
 *
 * 约定格式：
 * {"versionCode": 2, "versionName": "1.1", "url": "/phone-console.apk", "notes": "更新说明"}
 *
 * 404 / 网络失败 / JSON 坏掉都只提示，不抛异常。
 */
public class UpdateChecker {

    private static final String TAG = "UpdateChecker";
    private static final int CONNECT_TIMEOUT_MS = 4000;
    private static final int READ_TIMEOUT_MS = 6000;
    /** 安装未知来源应用的设置页（部分 ROM 上是这个 action） */
    private static final String ACTION_MANAGE_UNKNOWN_APP_SOURCES =
            "android.settings.MANAGE_UNKNOWN_APP_SOURCES";

    private final Activity activity;
    private final String host;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService pool = Executors.newSingleThreadExecutor();
    private final boolean silent;

    public UpdateChecker(Activity activity, String host) {
        this(activity, host, false);
    }

    public UpdateChecker(Activity activity, String host, boolean silent) {
        this.activity = activity;
        this.host = host;
        this.silent = silent;
    }

    /** 兼容构造：由 Prefs 取地址 */
    public UpdateChecker(Activity activity, String host, String pin) {
        this(activity, host, false);
    }

    /**
     * 拼基础地址：地址可能已经带 scheme（隧道是 https://xxx.trycloudflare.com），
     * 带了就原样用，没带才补 http://。以前这里写死 "http://"，隧道地址必然连不上。
     */
    private static String baseUrl(String host) {
        String h = host == null ? "" : host.trim();
        if (h.startsWith("http://") || h.startsWith("https://")) return h;
        return "http://" + h;
    }

    public void check(boolean silentCheck) {
        final boolean quiet = silentCheck || silent;
        if (host == null || host.trim().length() == 0) {
            if (!quiet) toast("还没设置控制台地址");
            return;
        }
        final String h = host.trim();
        if (!quiet) toast("正在检查更新…");
        pool.execute(new Runnable() {
            @Override
            public void run() {
                try {
                    JSONObject info = fetchJson(baseUrl(h) + "/app-version.json");
                    if (info == null) {
                        if (!quiet) ui.post(new Runnable() {
                            @Override
                            public void run() {
                                toast("未找到更新信息（服务器没有 app-version.json）");
                            }
                        });
                        return;
                    }
                    int remoteCode = info.optInt("versionCode", -1);
                    if (remoteCode < 0) {
                        if (!quiet) ui.post(new Runnable() {
                            @Override
                            public void run() {
                                toast("更新信息格式不对（缺 versionCode），已忽略");
                            }
                        });
                        return;
                    }
                    final int local = localVersionCode();
                    if (remoteCode <= local) {
                        if (!quiet) ui.post(new Runnable() {
                            @Override
                            public void run() {
                                toast("已经是最新版（本机 " + local + "）");
                            }
                        });
                        return;
                    }
                    final String remoteName = info.optString("versionName", String.valueOf(remoteCode));
                    String path = info.optString("url", "/phone-console.apk");
                    final String notes = info.optString("notes", "");
                    if (!path.startsWith("/")) path = "/" + path;
                    final String dlUrl = baseUrl(h) + path;
                    ui.post(new Runnable() {
                        @Override
                        public void run() {
                            showUpdateDialog(dlUrl, remoteName, remoteCode, notes);
                        }
                    });
                } catch (final Throwable t) {
                    Log.w(TAG, "check failed", t);
                    if (!quiet) ui.post(new Runnable() {
                        @Override
                        public void run() {
                            toast("检查更新失败：" + t.getClass().getSimpleName());
                        }
                    });
                }
            }
        });
    }

    private int localVersionCode() {
        try {
            PackageInfo pi = activity.getPackageManager()
                    .getPackageInfo(activity.getPackageName(), 0);
            return pi.versionCode;
        } catch (Throwable t) {
            Log.w(TAG, "localVersionCode", t);
            return 1;
        }
    }

    /** 拉 JSON；任何失败都返回 null（不抛） */
    private JSONObject fetchJson(String urlStr) {
        HttpURLConnection conn = null;
        InputStream in = null;
        try {
            URL url = new URL(urlStr);
            conn = (HttpURLConnection) url.openConnection();
            conn.setConnectTimeout(CONNECT_TIMEOUT_MS);
            conn.setReadTimeout(READ_TIMEOUT_MS);
            conn.setRequestMethod("GET");
            conn.setUseCaches(false);
            conn.setInstanceFollowRedirects(true);
            int code = conn.getResponseCode();
            if (code != 200) {
                Log.i(TAG, "app-version.json HTTP " + code);
                return null;
            }
            in = conn.getInputStream();
            String body = readAll(in);
            if (body == null || body.trim().length() == 0) return null;
            // 兼容 BOM
            if (body.charAt(0) == '\uFEFF') body = body.substring(1);
            return new JSONObject(body);
        } catch (Throwable t) {
            Log.w(TAG, "fetchJson " + urlStr, t);
            return null;
        } finally {
            try {
                if (in != null) in.close();
            } catch (Throwable ignored) {
            }
            if (conn != null) conn.disconnect();
        }
    }

    private void showUpdateDialog(final String url, final String versionName,
                                  final int versionCode, final String notes) {
        try {
            StringBuilder msg = new StringBuilder();
            msg.append("新版本 ").append(versionName)
                    .append("（versionCode ").append(versionCode).append("）");
            if (notes != null && notes.length() > 0) {
                msg.append("\n\n").append(notes);
            }
            new AlertDialog.Builder(activity)
                    .setTitle("发现新版本")
                    .setMessage(msg.toString())
                    .setPositiveButton("下载并安装", new DialogInterface.OnClickListener() {
                        @Override
                        public void onClick(DialogInterface d, int which) {
                            downloadAndInstall(url);
                        }
                    })
                    .setNegativeButton("以后再说", null)
                    .show();
        } catch (Throwable t) {
            Log.w(TAG, "showUpdateDialog", t);
            toast("有新版本可用，但弹窗失败");
        }
    }

    private void downloadAndInstall(final String url) {
        toast("正在下载新版本…");
        pool.execute(new Runnable() {
            @Override
            public void run() {
                File out = null;
                File tmp = null;
                HttpURLConnection conn = null;
                InputStream in = null;
                FileOutputStream fos = null;
                try {
                    File dir = new File(activity.getCacheDir(), "apk");
                    if (!dir.exists() && !dir.mkdirs()) {
                        ui.post(new Runnable() {
                            @Override
                            public void run() {
                                toast("无法创建缓存目录，下载取消");
                            }
                        });
                        return;
                    }
                    out = new File(dir, "phone-console-update.apk");
                    tmp = new File(dir, "phone-console-update.apk.part");
                    if (tmp.exists()) tmp.delete();
                    URL u = new URL(url);
                    conn = (HttpURLConnection) u.openConnection();
                    conn.setConnectTimeout(CONNECT_TIMEOUT_MS);
                    conn.setReadTimeout(15000);
                    conn.setRequestMethod("GET");
                    conn.setInstanceFollowRedirects(true);
                    conn.setUseCaches(false);
                    int code = conn.getResponseCode();
                    if (code != 200) {
                        final int c = code;
                        ui.post(new Runnable() {
                            @Override
                            public void run() {
                                toast("下载失败：服务器返回 HTTP " + c);
                            }
                        });
                        return;
                    }
                    in = new BufferedInputStream(conn.getInputStream());
                    fos = new FileOutputStream(tmp);
                    byte[] buf = new byte[8192];
                    int n;
                    long total = 0;
                    while ((n = in.read(buf)) > 0) {
                        fos.write(buf, 0, n);
                        total += n;
                    }
                    fos.flush();
                    fos.close();
                    fos = null;
                    if (total <= 0) {
                        ui.post(new Runnable() {
                            @Override
                            public void run() {
                                toast("下载到的文件是空的，已取消安装");
                            }
                        });
                        return;
                    }
                    // 粗校验：APK 必须是 zip（PK 开头），否则装不上还难排查
                    if (!looksLikeApk(tmp)) {
                        ui.post(new Runnable() {
                            @Override
                            public void run() {
                                toast("下载的文件不是 APK，已取消安装");
                            }
                        });
                        return;
                    }
                    // 校验通过再原子改名：保证 provider 永远读不到半个文件
                    if (out.exists()) out.delete();
                    if (!tmp.renameTo(out)) {
                        ui.post(new Runnable() {
                            @Override
                            public void run() {
                                toast("写入缓存失败（改名失败），下载取消");
                            }
                        });
                        return;
                    }
                    tmp = null;
                    final File apkFile = out;
                    ui.post(new Runnable() {
                        @Override
                        public void run() {
                            installApk(apkFile);
                        }
                    });
                } catch (final Throwable t) {
                    Log.w(TAG, "download failed", t);
                    ui.post(new Runnable() {
                        @Override
                        public void run() {
                            toast("下载失败：" + t.getClass().getSimpleName());
                        }
                    });
                } finally {
                    try {
                        if (fos != null) fos.close();
                    } catch (Throwable ignored) {
                    }
                    try {
                        if (in != null) in.close();
                    } catch (Throwable ignored) {
                    }
                    if (conn != null) conn.disconnect();
                    try {
                        if (tmp != null && tmp.exists()) tmp.delete();
                    } catch (Throwable ignored) {
                    }
                }
            }
        });
    }

    private boolean looksLikeApk(File f) {
        InputStream is = null;
        try {
            is = new java.io.FileInputStream(f);
            byte[] head = new byte[4];
            int n = is.read(head);
            return n == 4 && head[0] == 'P' && head[1] == 'K';
        } catch (Throwable t) {
            return false;
        } finally {
            try {
                if (is != null) is.close();
            } catch (Throwable ignored) {
            }
        }
    }

    /** Android 7+ 传 file:// 会 FileUriExposedException，这里走自己实现的 ApkProvider */
    private void installApk(File apk) {
        if (Build.VERSION.SDK_INT >= 26) {
            try {
                if (!activity.getPackageManager().canRequestPackageInstalls()) {
                    toast("请先允许「安装未知应用」，再回到菜单点一次「检查更新」");
                    openInstallPermissionSettings();
                    return;
                }
            } catch (Throwable t) {
                Log.w(TAG, "canRequestPackageInstalls", t);
            }
        }
        try {
            Uri uri = ApkProvider.getUriForFile(activity.getApplicationContext(), apk);
            if (uri == null) {
                toast("生成安装链接失败（文件不在缓存目录内）");
                return;
            }
            Intent it = new Intent(Intent.ACTION_VIEW);
            it.setDataAndType(uri, "application/vnd.android.package-archive");
            it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            it.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            activity.startActivity(it);
        } catch (Throwable t) {
            Log.w(TAG, "install intent failed", t);
            toast("安装失败：" + t.getClass().getSimpleName() + "（部分机型需手动在文件管理器里安装）");
        }
    }

    private void openInstallPermissionSettings() {
        try {
            if (Build.VERSION.SDK_INT >= 26) {
                Intent it = new Intent(ACTION_MANAGE_UNKNOWN_APP_SOURCES);
                it.setData(Uri.parse("package:" + activity.getPackageName()));
                activity.startActivity(it);
                return;
            }
        } catch (Throwable t) {
            Log.w(TAG, "openInstallPermissionSettings", t);
        }
        try {
            Intent it = new Intent(Settings.ACTION_SECURITY_SETTINGS);
            activity.startActivity(it);
        } catch (Throwable t) {
            toast("打不开设置页，请手动到「设置 → 应用 → 未知来源」里允许本 App 安装应用");
        }
    }

    private void toast(final String msg) {
        ui.post(new Runnable() {
            @Override
            public void run() {
                try {
                    Toast.makeText(activity, msg, Toast.LENGTH_SHORT).show();
                } catch (Throwable ignored) {
                }
            }
        });
    }

    private static String readAll(InputStream in) throws Exception {
        java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
        byte[] buf = new byte[4096];
        int n;
        while ((n = in.read(buf)) > 0) {
            bos.write(buf, 0, n);
            if (bos.size() > 256 * 1024) break; // 版本信息不可能这么大，防止对端刷数据
        }
        return new String(bos.toByteArray(), "UTF-8");
    }
}
