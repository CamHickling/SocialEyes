package org.socialeyes.pictogram.log

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Handler
import android.os.HandlerThread
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlin.math.abs

/**
 * Motion sensors to `sensors.csv` (docs/EVENT_LOG.md, "sensors.csv"): accelerometer
 * (m/s², with gravity), gyroscope (rad/s) and the game rotation vector as a unit
 * quaternion (no magnetometer, so no sudden jumps in heading near metal).
 * Sensors the phone lacks are left out and listed in session.json `sensors`.
 * Android stops delivering sensor events while the app is in the background.
 */
class MotionSensors(context: Context, private val log: SessionLog, private val hz: Int) {
    private val manager = context.getSystemService(SensorManager::class.java)
    private var thread: HandlerThread? = null
    // SensorEvent.timestamp is on the elapsed clock on current phones; a few use the
    // nanoTime base instead. Decided on the first event; 0 means "already elapsed".
    @Volatile private var offsetNs: Long? = null
    private val quaternion = FloatArray(4)

    private val sensors: Map<Sensor, String> = buildMap {
        manager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)?.let { put(it, "accel") }
        manager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)?.let { put(it, "gyro") }
        (manager.getDefaultSensor(Sensor.TYPE_GAME_ROTATION_VECTOR)
            ?: manager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR))?.let { put(it, "rotation") }
    }

    private val listener = object : SensorEventListener {
        override fun onSensorChanged(e: SensorEvent) {
            val name = sensors[e.sensor] ?: return
            val t = e.timestamp + (offsetNs ?: chooseOffset(e.timestamp))
            val v = e.values
            if (name == "rotation") {
                SensorManager.getQuaternionFromVector(quaternion, v) // w, x, y, z
                log.sensorRow(t, name, quaternion[1], quaternion[2], quaternion[3], quaternion[0])
            } else {
                log.sensorRow(t, name, v[0], v[1], v[2], null)
            }
        }

        override fun onAccuracyChanged(sensor: Sensor, accuracy: Int) {}
    }

    private fun chooseOffset(ts: Long): Long {
        val now = Clocks.elapsedNs()
        val offset = if (abs(now - ts) < 1_000_000_000L) 0L else Clocks.monotonicOffsetNs()
        offsetNs = offset
        return offset
    }

    fun start() {
        log.setMeta("sensors", buildJsonObject {
            put("hz", hz)
            sensors.forEach { (s, name) -> put(name, s.name) }
        })
        if (sensors.isEmpty()) return
        val t = HandlerThread("motion-sensors").apply { start() }
        thread = t
        val handler = Handler(t.looper)
        val periodUs = 1_000_000 / hz
        sensors.keys.forEach { manager.registerListener(listener, it, periodUs, handler) }
    }

    fun stop() {
        manager.unregisterListener(listener)
        thread?.quitSafely()
        thread = null
    }
}
