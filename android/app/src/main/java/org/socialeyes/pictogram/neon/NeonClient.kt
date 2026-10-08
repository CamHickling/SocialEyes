package org.socialeyes.pictogram.neon

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/** What Neon Companion reports about itself and the glasses. */
data class NeonStatus(
    val deviceName: String?,
    val deviceId: String?,
    /** Serial of the glasses' sensor module; null when no glasses are plugged in. */
    val moduleSerial: String?,
    val frameName: String?,
    /** Companion's recording action, e.g. START while recording; null when idle. */
    val recordingAction: String?,
) {
    val glassesConnected get() = moduleSerial != null
    val recording get() = recordingAction == "START"
}

/**
 * Neon Companion's real-time HTTP API. Companion runs on the same phone, so it is always at
 * 127.0.0.1:8080 and no discovery is needed. Calls block: run them off the main thread.
 *
 * Checked against Companion 2.9.48 (CAM-162): `recording:start` answers success and a new id
 * even when a recording is already running, and `stop_and_save` answers success when nothing
 * is recording, so callers check `status()` first instead of trusting those answers.
 */
class NeonClient(private val base: String = "http://127.0.0.1:8080/api", private val timeoutMs: Int = 3000) {

    fun status(): NeonStatus {
        val results = request("GET", "/status")["result"] as? JsonArray ?: throw IOException("Companion sent no status")
        val byModel = results.mapNotNull { it as? JsonObject }
            .filter { (it["model"] as? JsonPrimitive)?.contentOrNull != "Sensor" }
            .associate { (it["model"] as JsonPrimitive).content to (it["data"] as? JsonObject ?: JsonObject(emptyMap())) }
        fun field(model: String, key: String) = (byModel[model]?.get(key) as? JsonPrimitive)?.contentOrNull
        return NeonStatus(
            deviceName = field("Phone", "device_name"),
            deviceId = field("Phone", "device_id"),
            moduleSerial = field("Hardware", "module_serial")?.takeIf { it != "-1" },
            frameName = field("Hardware", "frame_name"),
            recordingAction = field("Recording", "action"),
        )
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
}
