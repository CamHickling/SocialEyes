package org.socialeyes.pictogram.log

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.database.ContentObserver
import android.os.BatteryManager
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.view.Surface
import android.view.WindowManager

/**
 * Session-quality events that don't come from the UI: thermal status, battery,
 * brightness and orientation (docs/EVENT_LOG.md, "Session quality").
 */
class DeviceMonitor(private val context: Context, private val log: SessionLog) {
    private val handler = Handler(Looper.getMainLooper())
    private val power = context.getSystemService(PowerManager::class.java)

    private val thermalListener = PowerManager.OnThermalStatusChangedListener { status ->
        log.event("thermal", fields = arrayOf("status" to thermalName(status)))
    }

    private val brightnessObserver = object : ContentObserver(handler) {
        override fun onChange(selfChange: Boolean) = logBrightness()
    }

    private val batteryTick = object : Runnable {
        override fun run() {
            logBattery()
            handler.postDelayed(this, 60_000)
        }
    }

    fun start() {
        // The listener is called once right away with the current status.
        power.addThermalStatusListener(context.mainExecutor, thermalListener)
        context.contentResolver.registerContentObserver(
            Settings.System.getUriFor(Settings.System.SCREEN_BRIGHTNESS), false, brightnessObserver,
        )
        logBrightness()
        logOrientation()
        batteryTick.run()
    }

    fun stop() {
        power.removeThermalStatusListener(thermalListener)
        context.contentResolver.unregisterContentObserver(brightnessObserver)
        handler.removeCallbacks(batteryTick)
    }

    private fun logBrightness() {
        val raw = runCatching { Settings.System.getInt(context.contentResolver, Settings.System.SCREEN_BRIGHTNESS) }
            .getOrNull() ?: return
        log.event("brightness", fields = arrayOf("value" to Math.round(raw / 255.0 * 1000) / 1000.0))
    }

    @Suppress("DEPRECATION") // Context.display needs API 30
    private fun logOrientation() {
        val rotation = when (context.getSystemService(WindowManager::class.java).defaultDisplay.rotation) {
            Surface.ROTATION_90 -> 90
            Surface.ROTATION_180 -> 180
            Surface.ROTATION_270 -> 270
            else -> 0
        }
        log.event("orientation", fields = arrayOf("rotation" to rotation))
    }

    private fun logBattery() {
        val intent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED)) ?: return
        val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
        val temp = intent.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Int.MIN_VALUE)
        log.event(
            "battery", fields = arrayOf(
                "level" to if (level >= 0 && scale > 0) Math.round(level * 100.0 / scale) / 100.0 else null,
                "temp_c" to if (temp != Int.MIN_VALUE) temp / 10.0 else null,
            )
        )
    }

    private fun thermalName(status: Int) = when (status) {
        PowerManager.THERMAL_STATUS_NONE -> "none"
        PowerManager.THERMAL_STATUS_LIGHT -> "light"
        PowerManager.THERMAL_STATUS_MODERATE -> "moderate"
        PowerManager.THERMAL_STATUS_SEVERE -> "severe"
        PowerManager.THERMAL_STATUS_CRITICAL -> "critical"
        PowerManager.THERMAL_STATUS_EMERGENCY -> "emergency"
        PowerManager.THERMAL_STATUS_SHUTDOWN -> "shutdown"
        else -> "none"
    }
}
