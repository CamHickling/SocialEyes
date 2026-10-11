package org.socialeyes.pictogram.neon

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** What Neon Companion reports about itself and the glasses. */
data class NeonStatus(
    val deviceName: String?,
    val deviceId: String?,
    /** Serial of the glasses' sensor module; null when no glasses are plugged in. */
    val moduleSerial: String?,
    val frameName: String?,
    /** Companion's recording action, e.g. START while recording; null when idle. */
    val recordingAction: String?,
    val batteryLevel: Int? = null,
    /** OK, LOW or CRITICAL. */
    val batteryState: String? = null,
    /** Free storage: OK, LOW or CRITICAL. */
    val memoryState: String? = null,
    /** Stream name (gaze, world, imu, eyes, eye_events) -> connected; absent if Companion didn't list it. */
    val streams: Map<String, Boolean> = emptyMap(),
) {
    val glassesConnected get() = moduleSerial != null
    val recording get() = recordingAction == "START"

    companion object {
        /** From /api/status: a list of {model, data}; Sensor entries come once per connection type. */
        fun parse(results: JsonArray): NeonStatus {
            val entries = results.mapNotNull { it as? JsonObject }
            fun model(e: JsonObject) = (e["model"] as? JsonPrimitive)?.contentOrNull
            fun data(e: JsonObject) = e["data"] as? JsonObject ?: JsonObject(emptyMap())
            val byModel = entries.filter { model(it) != "Sensor" }.associate { (model(it) ?: "") to data(it) }
            fun field(model: String, key: String) = (byModel[model]?.get(key) as? JsonPrimitive)?.contentOrNull
            val streams = mutableMapOf<String, Boolean>()
            entries.filter { model(it) == "Sensor" }.map(::data).forEach { d ->
                val name = (d["sensor"] as? JsonPrimitive)?.contentOrNull ?: return@forEach
                val connected = (d["connected"] as? JsonPrimitive)?.booleanOrNull ?: false
                streams[name] = (streams[name] ?: false) || connected
            }
            return NeonStatus(
                deviceName = field("Phone", "device_name"),
                deviceId = field("Phone", "device_id"),
                moduleSerial = field("Hardware", "module_serial")?.takeIf { it != "-1" && it != "unknown" },
                frameName = field("Hardware", "frame_name"),
                recordingAction = field("Recording", "action"),
                batteryLevel = field("Phone", "battery_level")?.toDoubleOrNull()?.toInt(),
                batteryState = field("Phone", "battery_state"),
                memoryState = field("Phone", "memory_state"),
                streams = streams,
            )
        }
    }
}

/** One scene camera control as Companion reports it: an integer range or a list of values. */
data class CameraControl(
    val name: String,
    val current: String,
    val min: Int? = null,
    val max: Int? = null,
    val allowed: List<String> = emptyList(),
) {
    /** Why `value` isn't allowed, or null if it is. */
    fun reject(value: String): String? = when {
        allowed.isNotEmpty() && value !in allowed -> "$name: $value is not one of ${allowed.joinToString()}"
        min != null && max != null -> value.toIntOrNull().let { v ->
            if (v == null || v < min || v > max) "$name: $value is outside $min..$max" else null
        }
        else -> null
    }

    companion object {
        fun parse(name: String, result: JsonObject): CameraControl {
            fun str(k: String) = (result[k] as? JsonPrimitive)?.contentOrNull
            fun int(k: String) = (result[k] as? JsonPrimitive)?.intOrNull
            return CameraControl(
                name = name,
                current = str("current_value") ?: "",
                min = int("value_min"),
                max = int("value_max"),
                allowed = (result["allowed_values"] as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.orEmpty(),
            )
        }
    }
}

/** A field of Companion's recording template (the form filled in for each recording). */
data class TemplateItem(val id: String, val title: String, val required: Boolean, val widget: String?)

/**
 * Neon Companion's real-time HTTP API. Companion runs on the same phone, so it is always at
 * 127.0.0.1:8080 and no discovery is needed. Calls block: run them off the main thread.
 *
 * Checked against Companion 2.9.48 (CAM-162): `recording:start` answers success and a new id
 * even when a recording is already running, and `stop_and_save` answers success when nothing
 * is recording, so callers check `status()` first instead of trusting those answers.
 * Camera control, template and calibration calls follow Pupil Labs' real-time API client 1.9.0
 * (not yet tried against the glasses).
 */
class NeonClient(private val host: String = "http://127.0.0.1:8080", private val timeoutMs: Int = 3000) {
    private val base = "$host/api"

    fun status(): NeonStatus {
        val results = request("GET", "/status")["result"] as? JsonArray ?: throw IOException("Companion sent no status")
        return NeonStatus.parse(results)
    }

    /** Starts a recording; returns its id. */
    fun startRecording(): String {
        val result = request("POST", "/recording:start")["result"] as? JsonObject
        return (result?.get("id") as? JsonPrimitive)?.contentOrNull
            ?: throw IOException("Companion didn't return a recording id")
    }

    fun stopAndSave() {
        request("POST", "/recording:stop_and_save")
    }

    /** Adds a named event to the running recording, at `unixNs` (Companion's clock is the phone's). */
    fun event(name: String, unixNs: Long) {
        request("POST", "/event", buildJsonObject {
            put("name", name)
            put("timestamp", unixNs)
        })
    }

    /** One scene camera control (ae_mode, man_exp, gain, brightness, contrast, gamma). */
    fun cameraControl(name: String): CameraControl {
        val result = request("GET", "/camera_control" + query("camera" to "world", name to ""))["result"] as? JsonObject
            ?: throw IOException("Companion sent no value for camera control $name")
        return CameraControl.parse(name, result)
    }

    fun cameraState(names: List<String> = CAMERA_CONTROLS): Map<String, CameraControl> = names.associateWith(::cameraControl)

    /** Sets scene camera controls, e.g. ae_mode=manual, man_exp=2000 (microseconds). */
    fun setCamera(values: Map<String, String>) {
        request("POST", "/camera_control" + query("camera" to "world", *values.toList().toTypedArray()))
    }

    /** The recording template currently selected in Companion. */
    fun templateItems(): List<TemplateItem> {
        val result = request("GET", "/template_def")["result"] as? JsonObject ?: return emptyList()
        return (result["items"] as? JsonArray).orEmpty().mapNotNull { it as? JsonObject }.mapNotNull { item ->
            fun str(k: String) = (item[k] as? JsonPrimitive)?.contentOrNull
            val id = str("id") ?: return@mapNotNull null
            TemplateItem(id, str("title") ?: "", (item["required"] as? JsonPrimitive)?.booleanOrNull ?: false, str("widget_type"))
        }
    }

    /** The template answers already entered, item id -> values. */
    fun templateData(): Map<String, List<String>> {
        val result = request("GET", "/template_data")["result"] as? JsonObject ?: return emptyMap()
        return result.mapValues { (_, v) -> values(v) }
    }

    /** Sends template answers. Companion wants every item, so the existing answers are kept. */
    fun fillTemplate(answers: Map<String, List<String>>) {
        val merged = templateData() + answers
        request("POST", "/template_data", buildJsonObject {
            merged.forEach { (id, v) -> put(id, JsonArray(v.ifEmpty { listOf("") }.map(::JsonPrimitive))) }
        })
    }

    /** The glasses' calibration (scene camera intrinsics and distortion), as Companion stores it. */
    fun calibration(): ByteArray {
        val conn = URL("$host/calibration.bin").openConnection() as HttpURLConnection
        try {
            conn.connectTimeout = timeoutMs
            conn.readTimeout = timeoutMs
            if (conn.responseCode !in 200..299) throw IOException("Companion: no calibration (HTTP ${conn.responseCode})")
            return conn.inputStream.use { it.readBytes() }
        } finally {
            conn.disconnect()
        }
    }

    private fun values(v: JsonElement): List<String> = when (v) {
        is JsonArray -> v.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
        is JsonPrimitive -> listOfNotNull(v.contentOrNull)
        else -> emptyList()
    }

    private fun query(vararg params: Pair<String, String>) =
        "?" + params.joinToString("&") { (k, v) -> URLEncoder.encode(k, "UTF-8") + "=" + URLEncoder.encode(v, "UTF-8") }

    private fun request(method: String, path: String, body: JsonObject? = null): JsonObject {
        val conn = URL(base + path).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = method
            conn.connectTimeout = timeoutMs
            conn.readTimeout = timeoutMs
            if (body != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                conn.outputStream.use { it.write(body.toString().toByteArray()) }
            }
            val code = conn.responseCode
            val text = (if (code in 200..299) conn.inputStream else conn.errorStream)?.bufferedReader()?.use { it.readText() }.orEmpty()
            val json = runCatching { Json.parseToJsonElement(text).jsonObject }.getOrNull()
            if (code !in 200..299) {
                val msg = (json?.get("message") as? JsonPrimitive)?.contentOrNull ?: text.take(200)
                throw IOException("Companion: $msg (HTTP $code)")
            }
            return json ?: JsonObject(emptyMap())
        } finally {
            conn.disconnect()
        }
    }

    companion object {
        val CAMERA_CONTROLS = listOf("ae_mode", "man_exp", "gain", "brightness")
    }
}
