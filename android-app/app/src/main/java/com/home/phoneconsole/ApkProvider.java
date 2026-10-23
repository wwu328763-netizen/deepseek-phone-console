package com.home.phoneconsole;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;

import java.io.File;
import java.io.FileNotFoundException;
import java.util.ArrayList;
import java.util.List;

/**
 * 极简 FileProvider：只把 getCacheDir()/apk/ 下**已存在**的文件暴露成 content:// Uri。
 *
 * 为什么不用 android.support.v4.content.FileProvider：
 * 本项目不允许引入任何第三方/支持库，androidx 无法编译，所以自己实现一个最小可用版本。
 * 用途只有一个：Android 7+ 把下载好的新 APK 通过 content:// 交给系统安装器
 * （直接传 file:// 会抛 FileUriExposedException）。
 */
public class ApkProvider extends ContentProvider {

    public static final String AUTHORITY = "com.home.phoneconsole.apk";
    /** 只允许访问这个子目录，路径写死在这里，不接受调用方传入任意路径 */
    private static final String SUBDIR = "apk";

    private static File apkDir(Context ctx) {
        return new File(ctx.getCacheDir(), SUBDIR);
    }

    /**
     * 生成 content:// Uri。schema 是我们自己定的：content://&lt;authority&gt;/apk/&lt;文件名&gt;
     * 传入的 file 必须位于 getCacheDir()/apk/ 目录内，否则返回 null（防止越权）。
     */
    public static Uri getUriForFile(Context ctx, File file) {
        if (file == null) return null;
        try {
            String dir = apkDir(ctx).getCanonicalPath();
            String path = file.getCanonicalPath();
            if (!path.startsWith(dir + File.separator)) return null;
            String name = file.getName();
            if (name.indexOf('/') >= 0 || name.indexOf('\\') >= 0) return null;
            return Uri.parse("content://" + AUTHORITY + "/" + SUBDIR + "/" + name);
        } catch (Throwable t) {
            return null;
        }
    }

    /** 由 Uri 还原 File；不在白名单内返回 null */
    private File resolve(Uri uri) {
        if (uri == null) return null;
        List<String> segs = uri.getPathSegments();
        if (segs == null || segs.size() != 2) return null;
        if (!SUBDIR.equals(segs.get(0))) return null;
        String name = segs.get(1);
        if (name == null || name.length() == 0) return null;
        if (name.indexOf('/') >= 0 || name.indexOf('\\') >= 0 || name.contains("..")) return null;
        File f = new File(apkDir(getContext()), name);
        try {
            String dir = apkDir(getContext()).getCanonicalPath();
            if (!f.getCanonicalPath().startsWith(dir + File.separator)) return null;
        } catch (Throwable t) {
            return null;
        }
        return f.exists() ? f : null;
    }

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        File f = resolve(uri);
        if (f == null) throw new FileNotFoundException("not found or not allowed: " + uri);
        return ParcelFileDescriptor.open(f, ParcelFileDescriptor.MODE_READ_ONLY);
    }

    @Override
    public String getType(Uri uri) {
        return "application/vnd.android.package-archive";
    }

    @Override
    public Cursor query(Uri uri, String[] projection, String selection,
                        String[] selectionArgs, String sortOrder) {
        return null; // 系统安装器不需要查询
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        throw new UnsupportedOperationException("read-only provider");
    }

    @Override
    public int delete(Uri uri, String selection, String[] selectionArgs) {
        throw new UnsupportedOperationException("read-only provider");
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] selectionArgs) {
        throw new UnsupportedOperationException("read-only provider");
    }

    /** 供调试用：列出当前暴露的文件名 */
    static List<String> listNames(Context ctx) {
        List<String> out = new ArrayList<String>();
        File[] fs = apkDir(ctx).listFiles();
        if (fs != null) {
            for (File f : fs) out.add(f.getName());
        }
        return out;
    }
}
