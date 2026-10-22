package org.socialeyes.pictogram.device

import android.app.Activity
import android.content.Context
import android.os.Build
import android.util.DisplayMetrics
import android.view.RoundedCorner
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonObject
import java.io.File

/**
 * The screen's real pixels per millimetre (CAM-227). Android reports xdpi/ydpi, but some phones
 * report them wrong, which would make the on-screen tags the wrong size and put gaze in the wrong
 * place on the screen. The ruler check (RulerScreen) measures two lines drawn at the reported dpi and
 * stores how far off they were; everything that sizes in millimetres goes through here, and every
 * session logs both the reported and the corrected dpi.
 */
object ScreenScale {
    private const val PREFS = "screen_scale"
    const val RULER_X_MM = 50.0
    const val RULER_Y_MM = 100.0

    /** The phone's own dpi, uncorrected. */
    fun reported(context: Context): Pair<Float, Float> =
        context.resources.displayMetrics.let { it.xdpi to it.ydpi }

    /** (x, y) factors from the ruler check: true dpi = reported dpi x factor (1, 1 if never checked). */
    fun factors(context: Context): Pair<Float, Float> = prefs(context).let { it.getFloat("x", 1f) to it.getFloat("y", 1f) }

    fun xdpi(context: Context): Float = reported(context).first * factors(context).first
    fun ydpi(context: Context): Float = reported(context).second * factors(context).second

    /** When the ruler check was done (epoch ms), or null. */
    fun checkedAt(context: Context): Long? = prefs(context).getLong("at", 0L).takeIf { it > 0 }

    /** Saves a ruler check: the lengths the researcher measured for the 50 mm and 100 mm lines. */
    fun save(context: Context, measuredXmm: Double, measuredYmm: Double) {
        prefs(context).edit()
            .putFloat("x", (RULER_X_MM / measuredXmm).toFloat())
            .putFloat("y", (RULER_Y_MM / measuredYmm).toFloat())
            .putFloat("measured_x_mm", measuredXmm.toFloat())
            .putFloat("measured_y_mm", measuredYmm.toFloat())
            .putLong("at", System.currentTimeMillis())
            .apply()
    }

    /** A measurement this far off the drawn length is a typo or the wrong line, not the screen. */
    fun plausible(drawnMm: Double, measuredMm: Double): Boolean = measuredMm in drawnMm * 0.8..drawnMm * 1.2

    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    /** The device facts the computer's loader checks the study's layout against (device_profile.json). */
    @Suppress("DEPRECATION") // getRealMetrics/defaultDisplay: the replacements need API 30
    fun profile(activity: Activity): JsonObject {
        val display = activity.windowManager.defaultDisplay
        val dm = DisplayMetrics().also { display.getRealMetrics(it) }
        val (fx, fy) = factors(activity)
        return buildJsonObject {
            put("manufacturer", Build.MANUFACTURER)
            put("model", Build.MODEL)
            put("android_sdk", Build.VERSION.SDK_INT)
            put("screen_width_px", dm.widthPixels)
            put("screen_height_px", dm.heightPixels)
            put("density", dm.density)
            put("xdpi_reported", dm.xdpi)
            put("ydpi_reported", dm.ydpi)
            put("xdpi", dm.xdpi * fx)
            put("ydpi", dm.ydpi * fy)
            checkedAt(activity)?.let { at ->
                putJsonObject("ruler_check") {
                    put("at", at)
                    put("measured_x_mm", prefs(activity).getFloat("measured_x_mm", 0f))
                    put("measured_y_mm", prefs(activity).getFloat("measured_y_mm", 0f))
                }
            }
            // rounded screen corners (Android 12+), radius in px; corners can clip a tag
            if (Build.VERSION.SDK_INT >= 31) {
                putJsonObject("rounded_corners") {
                    listOf("top_left" to RoundedCorner.POSITION_TOP_LEFT, "top_right" to RoundedCorner.POSITION_TOP_RIGHT,
                        "bottom_right" to RoundedCorner.POSITION_BOTTOM_RIGHT, "bottom_left" to RoundedCorner.POSITION_BOTTOM_LEFT)
                        .forEach { (name, pos) -> display.getRoundedCorner(pos)?.let { put(name, it.radius) } }
                }
            }
            // camera cut-outs (punch holes, notches), in screen px
            put("cutouts", buildJsonArray {
                display.cutout?.boundingRects?.forEach { r ->
                    add(buildJsonArray { add(kotlinx.serialization.json.JsonPrimitive(r.left)); add(kotlinx.serialization.json.JsonPrimitive(r.top))
                        add(kotlinx.serialization.json.JsonPrimitive(r.right)); add(kotlinx.serialization.json.JsonPrimitive(r.bottom)) })
                }
            })
        }
    }

    /** Writes device_profile.json into the app's files folder, where the loader reads it. */
    fun writeProfile(activity: Activity) {
        runCatching {
            val dir = activity.getExternalFilesDir(null) ?: return
            File(dir, "device_profile.json").writeText(profile(activity).toString())
        }
    }
}
