package com.home.phoneconsole;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;

import java.io.File;
import java.io.FileNotFoundException;
import java.util.List;

/**
 * 极简可写 FileProvider：只暴露 getCacheDir()/qr/ 目录，供系统相机把"扫到的二维码照片"写进来。
 *
 * 为什么不复用 ApkProvider：那个是**只读**的（系统安装器只需要读），而相机要**写**文件；
 * 拆成两个 Provider 可以让已经跑通的「自更新」链路完全不受影响。
 * 依旧不引入 androidx，自己实现最小可用版本（和 ApkProvider 同一套路子）。
 */
public class QrImageProvider extends ContentProvider {

    public static final String AUTHORITY = "com.home.phoneconsole.qr";
    /** 只允许这一个子目录，路径写死，不接受调用方传任意路径 */
    private static final String SUBDIR = "qr";

    private static File qrDir(Context ctx) {
        File d = new File(ctx.getCacheDir(), SUBDIR);
        if (!d.exists()) d.mkdirs();
        return d;
    }

    /** content://com.home.phoneconsole.qr/qr/<文件名>；文件必须位于 qr 目录内，否则返回 null */
    public static Uri getUriForFile(Context ctx, File file) {
        if (file == null) return null;
        try {
            String dir = qrDir(ctx).getCanonicalPath();
            String path = file.getCanonicalPath();
            if (!path.startsWith(dir + File.separator)) return null;
            String name = file.getName();
            if (name.indexOf('/') >= 0 || name.indexOf('\\') >= 0) return null;
            return Uri.parse("content://" + AUTHORITY + "/" + SUBDIR + "/" + name);
        } catch (Throwable t) {
            return null;
        }
    }

    private File resolve(Uri uri) {
        if (uri == null) return null;
        List<String> segs = uri.getPathSegments();
        if (segs == null || segs.size() != 2 || !SUBDIR.equals(segs.get(0))) return null;
        String name = segs.get(1);
        if (name == null || name.length() == 0) return null;
        if (name.indexOf('/') >= 0 || name.indexOf('\\') >= 0 || name.contains("..")) return null;
        return new File(qrDir(getContext()), name);
    }

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        File f = resolve(uri);
        if (f == null) throw new FileNotFoundException("not allowed: " + uri);
        boolean wantWrite = mode != null && (mode.contains("w") || mode.contains("rwt"));
        if (wantWrite) {
            File parent = f.getParentFile();
            if (parent != null && !parent.exists()) parent.mkdirs();
            return ParcelFileDescriptor.open(f,
                    ParcelFileDescriptor.MODE_CREATE | ParcelFileDescriptor.MODE_TRUNCATE
                            | ParcelFileDescriptor.MODE_READ_WRITE);
        }
        if (!f.exists()) throw new FileNotFoundException("not found: " + uri);
        return ParcelFileDescriptor.open(f, ParcelFileDescriptor.MODE_READ_ONLY);
    }

    @Override
    public String getType(Uri uri) {
        return "image/jpeg";
    }

    @Override
    public Cursor query(Uri uri, String[] projection, String selection,
                        String[] selectionArgs, String sortOrder) {
        return null;
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        throw new UnsupportedOperationException("no insert");
    }

    @Override
    public int delete(Uri uri, String selection, String[] selectionArgs) {
        return 0;
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] selectionArgs) {
        throw new UnsupportedOperationException("no update");
    }
}
