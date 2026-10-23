package com.home.phoneconsole;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.hardware.Camera;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.Vibrator;
import android.util.Log;
import android.view.Gravity;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import com.google.zxing.BarcodeFormat;
import com.google.zxing.BinaryBitmap;
import com.google.zxing.DecodeHintType;
import com.google.zxing.MultiFormatReader;
import com.google.zxing.PlanarYUVLuminanceSource;
import com.google.zxing.Result;
import com.google.zxing.common.HybridBinarizer;

import java.util.Collections;
import java.util.EnumMap;
import java.util.Map;

/**
 * 实时扫码：相机预览 + 逐帧解码（ZXing），对齐系统相机/微信扫码的体验。
 *
 * 为什么用 Camera1（android.hardware.Camera，虽然已标记 deprecated）：
 * 它的 setPreviewCallback 直接给 NV21，正好是 ZXing PlanarYUVLuminanceSource 要的格式，
 * 一个类就能搞定；Camera2 要自己处理 ImageReader/YUV_420_888 三个 plane，
 * 代码量翻几倍且更容易在个别机型上出问题。minSdk 21 起全平台可用。
 *
 * 解码节流：预览帧率通常 15~30fps，没必要每帧都解码（费电、发热），
 * 每 {@link #DECODE_INTERVAL_MS} 毫秒解一帧足够"随手一扫就中"。
 */
public class ScannerActivity extends Activity
        implements SurfaceHolder.Callback, Camera.PreviewCallback {

    public static final String EXTRA_TEXT = "text";
    public static final String EXTRA_ERROR = "error";
    private static final String TAG = "ScannerActivity";
    private static final int REQ_CAMERA_PERM = 2001;
    /** 解码节流间隔（毫秒） */
    private static final long DECODE_INTERVAL_MS = 120;

    private SurfaceView surface;
    private TextView hint;
    private Button torchBtn;

    private Camera camera;
    private Camera.Size previewSize;
    private int appliedDisplayOrientation = 0;   // 实际给相机设置的旋转角（0/90/180/270）
    private final MultiFormatReader reader = new MultiFormatReader();
    private final Handler ui = new Handler(Looper.getMainLooper());

    private volatile boolean decoding = false;
    private volatile boolean finished = false;
    private long lastDecode = 0L;
    private boolean torchOn = false;
    /** 逐帧解码复用缓冲（避免每帧几十万字节的分配） */
    private byte[] frameBuf = null;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        // 只认二维码：控制台只生成 QR，限定格式解码更快（省电、少误识别）
        Map<DecodeHintType, Object> hints = new EnumMap<DecodeHintType, Object>(DecodeHintType.class);
        hints.put(DecodeHintType.POSSIBLE_FORMATS, Collections.singletonList(BarcodeFormat.QR_CODE));
        reader.setHints(hints);

        try {   // 顶部不要出现黑条（与主界面一致）
            int flags = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
            getWindow().getDecorView().setSystemUiVisibility(flags);
            if (Build.VERSION.SDK_INT >= 21) {
                getWindow().setStatusBarColor(Color.parseColor("#E6E6E6"));
            }
        } catch (Throwable ignore) {
        }

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);

        surface = new SurfaceView(this);
        root.addView(surface, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        // 取景框（SurfaceView 的 surface 在窗口之下，所以这个遮罩能盖在预览上）
        root.addView(new Viewfinder(this), new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        LinearLayout top = new LinearLayout(this);
        top.setOrientation(LinearLayout.VERTICAL);
        top.setGravity(Gravity.CENTER_HORIZONTAL);
        top.setPadding(dp(20), dp(16), dp(20), dp(0));

        TextView title = new TextView(this);
        title.setText("对准电脑上的二维码");
        title.setTextColor(Color.WHITE);
        title.setTextSize(17f);
        title.setGravity(Gravity.CENTER);
        top.addView(title);

        hint = new TextView(this);
        hint.setText("识别到会自动填入地址和 PIN");
        hint.setTextColor(Color.parseColor("#D8FFFFFF"));
        hint.setTextSize(13f);
        hint.setGravity(Gravity.CENTER);
        hint.setPadding(0, dp(6), 0, 0);
        top.addView(hint);

        root.addView(top, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.TOP));

        torchBtn = new Button(this);
        torchBtn.setText("手电筒");
        torchBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                toggleTorch();
            }
        });
        FrameLayout.LayoutParams blp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL);
        blp.bottomMargin = dp(28);
        root.addView(torchBtn, blp);

        setContentView(root);

        surface.getHolder().addCallback(this);
        if (!hasCameraPermission()) {
            if (Build.VERSION.SDK_INT >= 23) {
                requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_CAMERA_PERM);
            }
        }
    }

    // ------------------------------------------------------------------
    // 权限
    // ------------------------------------------------------------------

    private boolean hasCameraPermission() {
        if (Build.VERSION.SDK_INT < 23) return true;
        return checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED;
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode != REQ_CAMERA_PERM) return;
        if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) {
            if (surface != null && surface.getHolder().getSurface() != null) openCamera();
        } else {
            fail("没有相机权限，无法实时扫码");
        }
    }

    // ------------------------------------------------------------------
    // Surface 生命周期
    // ------------------------------------------------------------------

    @Override
    public void surfaceCreated(SurfaceHolder holder) {
        if (!hasCameraPermission()) return;
        if (camera != null) {
            // surface 被重建（比如刚调过 SurfaceView 尺寸）：重新绑定并继续预览
            try {
                camera.setPreviewDisplay(holder);
                camera.setPreviewCallback(this);
                camera.startPreview();
                return;
            } catch (Throwable t) {
                Log.w(TAG, "rebind preview failed", t);
                releaseCamera();
            }
        }
        openCamera();
    }

    @Override
    public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {
        // 尺寸变化后重新对齐（不会改变已计算好的比例，纯保险）
        layoutSurfaceForPreview();
    }

    @Override
    public void surfaceDestroyed(SurfaceHolder holder) {
        releaseCamera();
    }

    private void openCamera() {
        if (camera != null) return;
        // 上一次打开的相机释放是异步的 —— 紧接着再进来立刻 open 会失败，
        // 真机现象就是"再次打开扫码后一片黑、扫不到任何东西"。所以重试几次。
        for (int attempt = 0; attempt < 4 && camera == null; attempt++) {
            try {
                camera = Camera.open();          // 后置摄像头
            } catch (Throwable t) {
                Log.w(TAG, "Camera.open failed (attempt " + attempt + ")", t);
                if (attempt < 3) {
                    try {
                        Thread.sleep(150);
                    } catch (InterruptedException ignore) {
                    }
                }
            }
        }
        if (camera == null) {
            fail("打不开相机，已切回拍照识别");
            return;
        }
        try {
            Camera.Parameters p = camera.getParameters();

            // 预览尺寸：在 640x480 ~ 1280x960 里挑"旋转后长宽比最接近屏幕"的那个。
            // 以前固定挑最小的 640x480（4:3），被硬撑到手机竖屏比例上就拉变形了。
            boolean swap = isPortraitSwap();
            int[] wh = screenSize();
            float target = swap ? (float) wh[1] / wh[0] : (float) wh[0] / wh[1];
            Camera.Size best = null;
            float bestDiff = Float.MAX_VALUE;
            for (Camera.Size s : p.getSupportedPreviewSizes()) {
                long area = (long) s.width * s.height;
                if (area < 640L * 480L || area > 1280L * 960L) continue;
                float ratio = swap ? (float) s.width / s.height : (float) s.height / s.width;
                float diff = Math.abs(ratio - target);
                if (diff < bestDiff) {
                    bestDiff = diff;
                    best = s;
                }
            }
            if (best != null) {
                previewSize = best;
                p.setPreviewSize(best.width, best.height);
            } else {
                previewSize = p.getPreviewSize();
            }
            // 连续对焦：不自动对焦的话近距离二维码经常糊成一团
            try {
                if (p.getSupportedFocusModes() != null
                        && p.getSupportedFocusModes().contains(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE)) {
                    p.setFocusMode(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE);
                }
            } catch (Throwable ignore) {
            }
            // 预览格式优先 NV21（ZXing 直接吃）
            try {
                p.setPreviewFormat(android.graphics.ImageFormat.NV21);
            } catch (Throwable ignore) {
            }
            camera.setParameters(p);

            // 关键：让预览按手机竖直方向正着显示。
            // 不设 displayOrientation 的话画面会横躺 90°，手指移动方向也和画面相反。
            applyDisplayOrientation();
            // 先按"旋转后画面"的长宽比调好 SurfaceView 尺寸，再绑定预览：
            // 尺寸变化会让 surface 重建，所以绑定必须在调尺寸之后做（重建时 surfaceCreated 会重绑）。
            layoutSurfaceForPreview();
            camera.setPreviewDisplay(surface.getHolder());
            camera.setPreviewCallback(this);
            camera.startPreview();
        } catch (Throwable t) {
            Log.w(TAG, "camera setup failed", t);
            fail("相机初始化失败，已切回拍照识别");
        }
    }

    /** 预览画面是否需要交换长宽：由"实际给相机的旋转角"决定。
        之前用屏幕旋转判断：手机竖持时 screen rotation=0 但预览必须转 90°，
        于是 SurfaceView 被按横向比例摆放，画面被硬拉成横的（真机踩过）。 */
    private boolean isPortraitSwap() {
        if (appliedDisplayOrientation % 180 == 90) return true;
        int rot = displayRotationDegrees();
        return rot == 90 || rot == 270;
    }

    private int displayRotationDegrees() {
        try {
            int r = getWindowManager().getDefaultDisplay().getRotation();
            switch (r) {
                case android.view.Surface.ROTATION_90:
                    return 90;
                case android.view.Surface.ROTATION_180:
                    return 180;
                case android.view.Surface.ROTATION_270:
                    return 270;
                default:
                    return 0;
            }
        } catch (Throwable t) {
            return 90;
        }
    }

    /** 按传感器方向 + 屏幕旋转算出预览该转多少度（标准 Camera1 算法） */
    private void applyDisplayOrientation() {
        try {
            Camera.CameraInfo info = new Camera.CameraInfo();
            Camera.getCameraInfo(0, info);
            int degrees = displayRotationDegrees();
            int result;
            if (info.facing == Camera.CameraInfo.CAMERA_FACING_FRONT) {
                result = (info.orientation + degrees) % 360;
                result = (360 - result) % 360;      // 前置要镜像
            } else {
                result = (info.orientation - degrees + 360) % 360;
            }
            appliedDisplayOrientation = result;
            camera.setDisplayOrientation(result);
        } catch (Throwable t) {
            Log.w(TAG, "setDisplayOrientation", t);
            try {
                camera.setDisplayOrientation(90);
            } catch (Throwable ignore) {
            }
        }
    }

    private int[] screenSize() {
        try {
            android.util.DisplayMetrics dm = new android.util.DisplayMetrics();
            getWindowManager().getDefaultDisplay().getMetrics(dm);
            if (dm.widthPixels > 0 && dm.heightPixels > 0) {
                return new int[]{dm.widthPixels, dm.heightPixels};
            }
        } catch (Throwable ignore) {
        }
        return new int[]{1080, 1920};
    }

    /** SurfaceView 按"预览旋转后的长宽比"居中摆放，保持画面不变形 */
    private void layoutSurfaceForPreview() {
        try {
            if (surface == null || previewSize == null) return;
            boolean swap = isPortraitSwap();
            float dispW = swap ? previewSize.height : previewSize.width;
            float dispH = swap ? previewSize.width : previewSize.height;
            if (dispW <= 0 || dispH <= 0) return;
            int[] wh = screenSize();
            // 取 max：画面按比例放大到铺满屏幕，多出来的部分被裁掉（扫描器的最佳观感），
            // 用 min 会留黑边、而且某些机器上 SurfaceView 会被再拉伸一次。
            float scale = Math.max(wh[0] / dispW, wh[1] / dispH);
            int w = Math.round(dispW * scale);
            int h = Math.round(dispH * scale);
            ViewGroup.LayoutParams raw = surface.getLayoutParams();
            if (!(raw instanceof FrameLayout.LayoutParams)) return;
            FrameLayout.LayoutParams lp = (FrameLayout.LayoutParams) raw;
            lp.width = w;
            lp.height = h;
            lp.gravity = Gravity.CENTER;
            surface.setLayoutParams(lp);
        } catch (Throwable t) {
            Log.w(TAG, "layoutSurfaceForPreview", t);
        }
    }

    private void releaseCamera() {
        if (camera == null) return;
        try {
            camera.setPreviewCallback(null);
        } catch (Throwable ignore) {
        }
        try {
            camera.stopPreview();
        } catch (Throwable ignore) {
        }
        try {
            camera.release();
        } catch (Throwable ignore) {
        }
        camera = null;
    }

    private void toggleTorch() {
        if (camera == null) return;
        try {
            Camera.Parameters p = camera.getParameters();
            if (p.getSupportedFlashModes() == null
                    || !p.getSupportedFlashModes().contains(Camera.Parameters.FLASH_MODE_TORCH)) {
                toast("这台设备的相机不支持手电筒");
                return;
            }
            torchOn = !torchOn;
            p.setFlashMode(torchOn ? Camera.Parameters.FLASH_MODE_TORCH : Camera.Parameters.FLASH_MODE_OFF);
            camera.setParameters(p);
            torchBtn.setText(torchOn ? "关闭手电筒" : "手电筒");
        } catch (Throwable t) {
            Log.w(TAG, "toggleTorch", t);
        }
    }

    // ------------------------------------------------------------------
    // 逐帧解码
    // ------------------------------------------------------------------

    @Override
    public void onPreviewFrame(byte[] data, Camera cam) {
        if (data == null || finished) return;
        long now = System.currentTimeMillis();
        if (decoding || now - lastDecode < DECODE_INTERVAL_MS) return;   // 节流
        int w = previewSize != null ? previewSize.width : 0;
        int h = previewSize != null ? previewSize.height : 0;
        if (w <= 0 || h <= 0) {
            try {
                Camera.Size s = cam.getParameters().getPreviewSize();
                w = s.width;
                h = s.height;
            } catch (Throwable t) {
                return;
            }
        }
        // 复用同一块缓冲：每帧 clone 一兆多在低端机上会明显卡顿/发热
        if (frameBuf == null || frameBuf.length < data.length) {
            frameBuf = new byte[data.length];
        }
        System.arraycopy(data, 0, frameBuf, 0, data.length);
        decoding = true;
        lastDecode = now;

        final int fw = w;
        final int fh = h;

        new Thread(new Runnable() {
            @Override
            public void run() {
                String text = decode(frameBuf, fw, fh);
                decoding = false;
                if (text != null && !finished) onScanned(text);
            }
        }, "qr-live-decode").start();
    }

    /** 用 ZXing 解一帧 NV21；没识别到返回 null（属正常，继续下一帧） */
    private String decode(byte[] nv21, int width, int height) {
        try {
            PlanarYUVLuminanceSource src =
                    new PlanarYUVLuminanceSource(nv21, width, height, 0, 0, width, height, false);
            BinaryBitmap bitmap = new BinaryBitmap(new HybridBinarizer(src));
            Result r = reader.decodeWithState(bitmap);
            return r == null ? null : r.getText();
        } catch (Throwable t) {
            return null;      // NotFoundException / ChecksumException 都很常见
        }
    }

    private void onScanned(final String text) {
        finished = true;
        try {
            Vibrator v = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);
            if (v != null) v.vibrate(60);
        } catch (Throwable ignore) {
        }
        releaseCamera();
        ui.post(new Runnable() {
            @Override
            public void run() {
                Intent out = new Intent();
                out.putExtra(EXTRA_TEXT, text);
                setResult(RESULT_OK, out);
                finish();
            }
        });
    }

    /** 出错了：把原因带回去，让设置页自动回退到"拍照识别" */
    private void fail(final String message) {
        if (finished) return;
        finished = true;
        releaseCamera();
        ui.post(new Runnable() {
            @Override
            public void run() {
                Intent out = new Intent();
                out.putExtra(EXTRA_ERROR, message);
                setResult(RESULT_CANCELED, out);
                finish();
            }
        });
    }

    @Override
    protected void onPause() {
        super.onPause();
        releaseCamera();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (surface != null && surface.getHolder().getSurface() != null && hasCameraPermission()) {
            openCamera();
        }
    }

    @Override
    public void onBackPressed() {
        finished = true;
        releaseCamera();
        super.onBackPressed();
    }

    // ------------------------------------------------------------------
    // 工具
    // ------------------------------------------------------------------

    private void toast(String text) {
        Toast.makeText(this, text, Toast.LENGTH_SHORT).show();
    }

    private int dp(int v) {
        return (int) (v * getResources().getDisplayMetrics().density);
    }

    /** 取景框：四周压暗 + 中间方框四角，纯代码绘制（不依赖 layout xml） */
    private class Viewfinder extends View {
        private final Paint dim = new Paint();
        private final Paint corner = new Paint(Paint.ANTI_ALIAS_FLAG);

        Viewfinder(Context ctx) {
            super(ctx);
            dim.setColor(0x99000000);
            corner.setColor(Color.parseColor("#07C160"));
            corner.setStyle(Paint.Style.STROKE);
            corner.setStrokeWidth(dp(3));
        }

        @Override
        protected void onDraw(Canvas canvas) {
            int w = getWidth();
            int h = getHeight();
            int side = (int) (Math.min(w, h) * 0.68);
            int left = (w - side) / 2;
            int top = (h - side) / 2;
            canvas.drawRect(0, 0, w, top, dim);
            canvas.drawRect(0, top + side, w, h, dim);
            canvas.drawRect(0, top, left, top + side, dim);
            canvas.drawRect(left + side, top, w, top + side, dim);

            int len = Math.max(dp(18), side / 7);
            canvas.drawLine(left, top, left + len, top, corner);
            canvas.drawLine(left, top, left, top + len, corner);
            canvas.drawLine(left + side, top, left + side - len, top, corner);
            canvas.drawLine(left + side, top, left + side, top + len, corner);
            canvas.drawLine(left, top + side, left + len, top + side, corner);
            canvas.drawLine(left, top + side, left, top + side - len, corner);
            canvas.drawLine(left + side, top + side, left + side - len, top + side, corner);
            canvas.drawLine(left + side, top + side, left + side, top + side - len, corner);
        }
    }
}
