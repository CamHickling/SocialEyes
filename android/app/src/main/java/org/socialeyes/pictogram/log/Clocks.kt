package org.socialeyes.pictogram.log

import android.os.SystemClock
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Every logged time is `SystemClock.elapsedRealtimeNanos()` (docs/EVENT_LOG.md, "Clocks").
 *
 * MotionEvent and Choreographer/Compose frame times are on the `System.nanoTime()` base,
 * which stops during deep sleep; convert them with [fromMonotonic].
 */
object Clocks {
    fun elapsedNs(): Long = SystemClock.elapsedRealtimeNanos()

    /** Offset to add to a `System.nanoTime()` / `uptimeMillis`-based time. Sample it when handling the event. */
    fun monotonicOffsetNs(): Long = SystemClock.elapsedRealtimeNanos() - System.nanoTime()

    fun fromMonotonic(monotonicNs: Long): Long = monotonicNs + monotonicOffsetNs()

    /** All clock bases read back-to-back, for session.json. */
    fun snapshot(): JsonObject {
        val elapsed = SystemClock.elapsedRealtimeNanos()
        val uptime = System.nanoTime()
        val wall = System.currentTimeMillis()
        return buildJsonObject {
            put("elapsed_ns", elapsed)
            put("uptime_ns", uptime)
            put("wall_ms", wall)
        }
    }
}
