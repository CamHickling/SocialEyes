package org.socialeyes.pictogram.log

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.socialeyes.pictogram.study.StudyJson
import java.io.BufferedWriter
import java.io.File
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * Writes one session folder in the format of docs/EVENT_LOG.md.
 *
 * Rows are buffered and flushed once a second, so a crash loses at most a
 * second of data. session.json is written at the start and rewritten whenever
 * it changes; it only gets `end` when the session finishes normally or is aborted.
 * All methods are thread-safe.
 */
class SessionLog(val dir: File, initialMeta: JsonObject, logTouches: Boolean) {
    private val lock = Any()
    private val meta = LinkedHashMap<String, JsonElement>(initialMeta)
    private val events = writer("events.jsonl")
    private val viewport = csv("viewport.csv", VIEWPORT_COLUMNS)
    private val touch = if (logTouches) csv("touch.csv", TOUCH_COLUMNS) else null
    private var video: CsvWriter? = null // video.csv, only when reels are watched
    private val flusher = Executors.newSingleThreadScheduledExecutor()

    @Volatile
    var finished = false
        private set

    init {
        writeMeta()
        flusher.scheduleWithFixedDelay(::flush, 1, 1, TimeUnit.SECONDS)
    }

    fun event(type: String, tNs: Long = Clocks.elapsedNs(), vararg fields: Pair<String, Any?>) {
        val obj = buildJsonObject {
            put("t_ns", tNs)
            put("type", type)
            for ((k, v) in fields) put(k, toJson(v))
        }
        synchronized(lock) {
            if (finished) return
            events.write(obj.toString())
            events.write("\n")
        }
    }

    fun touchRow(
        tNs: Long, action: String, pointerId: Int, x: Float, y: Float,
        pressure: Float?, size: Float?, major: Float?, minor: Float?, stepId: String,
    ) {
        val w = touch ?: return
        synchronized(lock) {
            if (finished) return
            w.row(tNs, action, pointerId, f1(x), f1(y), f3(pressure), f4(size), f1(major), f1(minor), stepId)
        }
    }

    /** One drawn frame of a playing (or paused) reel: where in the video it was. */
    fun videoRow(tNs: Long, reelId: String, positionMs: Long, playing: Boolean) {
        synchronized(lock) {
            if (finished) return
            val w = video ?: csv("video.csv", VIDEO_COLUMNS).also { video = it }
            w.row(tNs, reelId, positionMs, if (playing) 1 else 0)
        }
    }

    fun viewportFrame(tNs: Long, frame: Long, scrollY: Float) {
        synchronized(lock) {
            if (!finished) viewport.row(tNs, frame, f1(scrollY), "", "frame", "", "", "", "")
        }
    }

    fun viewportElement(tNs: Long, frame: Long, postId: String, element: String, r: ScreenRect) {
        synchronized(lock) {
            if (!finished) viewport.row(tNs, frame, "", postId, element, f1(r.left), f1(r.top), f1(r.right), f1(r.bottom))
        }
    }

    /** Adds or replaces a top-level session.json field and rewrites the file. */
    fun setMeta(key: String, value: JsonElement) {
        synchronized(lock) {
            if (finished) return
            meta[key] = value
            writeMeta()
        }
    }

    /** `reason` is `completed` or `aborted`. Closes every file; later calls are ignored. */
    fun finish(reason: String) {
        synchronized(lock) {
            if (finished) return
            meta["end"] = buildJsonObject {
                put("reason", reason)
                put("clock", Clocks.snapshot())
            }
            writeMeta()
            finished = true
            listOfNotNull(events, viewport.out, touch?.out, video?.out).forEach { it.close() }
        }
        flusher.shutdown()
    }

    private fun flush() {
        synchronized(lock) {
            if (finished) return
            listOfNotNull(events, viewport.out, touch?.out, video?.out).forEach { it.flush() }
        }
    }

    private fun writeMeta() {
        val tmp = File(dir, "session.json.tmp")
        tmp.writeText(prettyJson.encodeToString(JsonObject.serializer(), JsonObject(meta)) + "\n")
        if (!tmp.renameTo(File(dir, "session.json"))) error("could not write session.json")
    }

    private fun writer(name: String) = File(dir, name).bufferedWriter(Charsets.UTF_8)

    private fun csv(name: String, columns: List<String>) = CsvWriter(writer(name)).also { it.row(*columns.toTypedArray()) }

    private class CsvWriter(val out: BufferedWriter) {
        fun row(vararg values: Any?) {
            values.forEachIndexed { i, v ->
                if (i > 0) out.write(",")
                out.write(escape(v?.toString() ?: ""))
            }
            out.write("\n")
        }

        private fun escape(s: String) =
            if (s.any { it == ',' || it == '"' || it == '\n' || it == '\r' }) "\"" + s.replace("\"", "\"\"") + "\"" else s
    }

    companion object {
        // Must match python/src/socialeyes/session/io.py
        val TOUCH_COLUMNS = listOf("t_ns", "action", "pointer_id", "x_px", "y_px", "pressure", "size", "major_px", "minor_px", "step_id")
        val VIDEO_COLUMNS = listOf("t_ns", "reel_id", "position_ms", "playing")
        val VIEWPORT_COLUMNS = listOf("t_ns", "frame", "scroll_y", "post_id", "element", "left", "top", "right", "bottom")

        private val prettyJson = Json(StudyJson) { prettyPrint = true }

        private fun fmt(v: Float?, digits: Int) = if (v == null || v.isNaN()) "" else String.format(Locale.ROOT, "%.${digits}f", v)
        private fun f1(v: Float?) = fmt(v, 1)
        private fun f3(v: Float?) = fmt(v, 3)
        private fun f4(v: Float?) = fmt(v, 4)

        fun toJson(v: Any?): JsonElement = when (v) {
            null -> JsonNull
            is JsonElement -> v
            is String -> JsonPrimitive(v)
            is Number -> JsonPrimitive(v)
            is Boolean -> JsonPrimitive(v)
            is Map<*, *> -> JsonObject(v.entries.associate { (k, x) -> k.toString() to toJson(x) })
            is Iterable<*> -> JsonArray(v.map(::toJson))
            else -> JsonPrimitive(v.toString())
        }
    }
}

/** A rectangle in physical screen pixels, not clipped to the screen. */
data class ScreenRect(val left: Float, val top: Float, val right: Float, val bottom: Float) {
    fun intersects(o: ScreenRect) = left < o.right && o.left < right && top < o.bottom && o.top < bottom
    fun offset(dx: Float, dy: Float) = ScreenRect(left + dx, top + dy, right + dx, bottom + dy)
    fun toJson() = SessionLog.toJson(listOf(left, top, right, bottom))
}
