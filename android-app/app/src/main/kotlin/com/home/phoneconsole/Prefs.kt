package com.home.phoneconsole

import android.content.Context
import android.content.SharedPreferences

/**
 * SharedPreferences 封装：保存控制台地址、PIN 与历史地址列表。
 * 全部是轻量同步读写。历史列表存成单条 "\n" 分隔字符串，保证顺序稳定。
 *
 * 由原 Prefs.java 逐行移植成 Kotlin：
 *  - `object` + `@JvmStatic` 保证 Java 侧 `Prefs.getHost(ctx)` 的调用点一行都不用改；
 *  - 行为、默认值、历史条数上限、null 处理与原实现完全一致。
 */
object Prefs {

    private const val FILE = "phone_console"
    private const val KEY_HOST = "host"
    private const val KEY_PIN = "pin"
    private const val KEY_HISTORY = "history"
    private const val KEY_REQUIRE_LOGIN = "require_login"
    private const val HISTORY_MAX = 8

    private fun sp(ctx: Context): SharedPreferences =
        ctx.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    /** 等价于 androidx.core 的 sp.edit {} 扩展，但不引入 AndroidX */
    private inline fun edit(ctx: Context, block: SharedPreferences.Editor.() -> Unit) {
        val e = sp(ctx).edit()
        e.block()
        e.apply()
    }

    /** 已拆解好的主机地址，例如 192.168.1.23:8787 或 https://xxx.trycloudflare.com */
    @JvmStatic
    fun getHost(ctx: Context): String {
        val v = sp(ctx).getString(KEY_HOST, "")
        // 顺手迁移老版本存下的隧道地址（曾被误加 :8787），用户升级后无需重填
        return if (v == null) "" else SetupActivity.migrateStoredHost(v)
    }

    /** 8 位 PIN，可能为空字符串（留空则由网页自己提示输入） */
    @JvmStatic
    fun getPin(ctx: Context): String {
        val v = sp(ctx).getString(KEY_PIN, "")
        return v?.trim() ?: ""
    }

    @JvmStatic
    fun isConfigured(ctx: Context): Boolean = getHost(ctx).isNotEmpty()

    @JvmStatic
    fun save(ctx: Context, host: String?, pin: String?) {
        edit(ctx) {
            putString(KEY_HOST, host?.trim() ?: "")
            putString(KEY_PIN, pin?.trim() ?: "")
        }
        addHistory(ctx, host)
    }

    /** 历史地址：最近使用排在最前，去重，最多 [HISTORY_MAX] 条 */
    @JvmStatic
    fun addHistory(ctx: Context, host: String?) {
        if (host == null) return
        val h = host.trim()
        if (h.isEmpty()) return
        val list = getHistory(ctx).toMutableList()
        list.remove(h)
        list.add(0, h)
        while (list.size > HISTORY_MAX) {
            list.removeAt(list.size - 1)
        }
        edit(ctx) { putString(KEY_HISTORY, list.joinToString("\n")) }
    }

    /** 按「最近使用优先」排序的历史列表 */
    @JvmStatic
    fun getHistory(ctx: Context): List<String> {
        val list = ArrayList<String>()
        val raw = sp(ctx).getString(KEY_HISTORY, "")
        if (raw == null || raw.isEmpty()) return list
        for (part in raw.split("\n")) {
            val p = part.trim()
            if (p.isNotEmpty() && !list.contains(p)) list.add(p)
        }
        return list
    }

    /** 启动时是否强制显示网页登录页（URL 不带 PIN）。默认 false：连过就直接进。 */
    @JvmStatic
    fun getRequireLogin(ctx: Context): Boolean = sp(ctx).getBoolean(KEY_REQUIRE_LOGIN, false)

    @JvmStatic
    fun setRequireLogin(ctx: Context, on: Boolean) {
        edit(ctx) { putBoolean(KEY_REQUIRE_LOGIN, on) }
    }

    @JvmStatic
    fun clearAll(ctx: Context) {
        edit(ctx) { clear() }
    }
}
