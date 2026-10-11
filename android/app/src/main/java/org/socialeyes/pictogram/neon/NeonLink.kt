package org.socialeyes.pictogram.neon

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonObject
import org.socialeyes.pictogram.log.Clocks
import org.socialeyes.pictogram.log.SessionLog
import java.io.File
import java.io.IOException
import java.time.Instant

/** Why the eye tracker can't record: shown to the researcher before the session starts. */
class NeonNotReady(message: String) : Exception(message)

/**
 * Starts the Neon recording before a session (see [start]), then belongs to that session:
 * pairs the recording with it in session.json (with the scene camera settings, template answers,
 * checklist and the glasses' calibration), logs `neon` events, marks every step in the
 * recording, watches the glasses and their streams, and stops and saves the recording when the
 * session ends, putting back any scene camera settings it changed.
 */
class NeonLink private constructor(
    private val client: NeonClient,
    val recordingId: String,
    private val preflight: Preflight,
    private val checklist: List<Pair<String, Boolean>>,
    private val calibration: ByteArray?,
    private val restoreCamera: Map<String, String>,
    private val startedNs: Long,
) {
    private val status get() = preflight.status
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var log: SessionLog? = null
    private var monitor: Job? = null
    private var stopped = false

    /** Pairs the running recording with the session and starts watching it. */
    fun attach(log: SessionLog, sessionUid: String, checkEveryS: Double) {
        this.log = log
        val calib = calibration?.let { bytes ->
            runCatching { File(log.dir, CALIBRATION_FILE).writeBytes(bytes) }
            runCatching { SceneCalibration.parse(bytes) }.getOrNull()
        }
        log.setMeta("neon", buildJsonObject {
            put("recording_id", recordingId)
            status.deviceName?.let { put("device_name", it) }
            status.deviceId?.let { put("device_id", it) }
            status.moduleSerial?.let { put("module_serial", it) }
            status.frameName?.let { put("frame_name", it) }
            status.batteryLevel?.let { put("battery_level", it) }
            preflight.camera?.let { cam -> putJsonObject("scene_camera_before") { cam.forEach { (k, c) -> put(k, c.current) } } }
            if (preflight.exposureChange.isNotEmpty()) {
                putJsonObject("scene_camera_set") { preflight.exposureChange.forEach { (k, v) -> put(k, v) } }
            }
            if (preflight.templateFilled.isNotEmpty()) put("template_filled", JsonArray(preflight.templateFilled.map(::JsonPrimitive)))
            if (checklist.isNotEmpty()) put("checklist", buildJsonArray {
                checklist.forEach { (item, ok) -> add(buildJsonObject { put("item", item); put("confirmed", ok) }) }
            })
            if (preflight.warnings.isNotEmpty()) put("warnings", JsonArray(preflight.warnings.map(::JsonPrimitive)))
            calib?.let {
                putJsonObject("scene_calibration") {
                    put("file", CALIBRATION_FILE)
                    put("serial", it.serial)
                    put("fx", it.fx); put("fy", it.fy); put("cx", it.cx); put("cy", it.cy)
                }
            }
        })
        log.event("neon", startedNs, "status" to "connected", "module_serial" to status.moduleSerial)
        log.event("neon", startedNs, "status" to "recording_start", "recording_id" to recordingId)
        mark("socialeyes.session_start $sessionUid")
        monitor = scope.launch { watch((checkEveryS * 1000).toLong().coerceAtLeast(500)) }
    }

    /** Adds an event to the Neon recording (e.g. a step start), so the two can be lined up. */
    fun mark(name: String) {
        val t = unixNs()
        scope.launch { runCatching { client.event(name, t) } }
    }

    /**
     * Stops and saves the recording. Blocks for at most a few seconds (Companion is on this phone),
     * because the session log closes right after and the result belongs in it.
     */
    fun stop(reason: String) {
        if (stopped) return
        stopped = true
        monitor?.cancel()
        var restored: Boolean? = null
        val error: String? = runBlocking(Dispatchers.IO) {
            val result = withTimeoutOrNull(5000) {
                runCatching {
                    client.event("socialeyes.session_end $reason", unixNs())
                    if (!client.status().recording) throw IOException("the recording had already stopped")
                    client.stopAndSave()
                }.fold({ OK }, { it.message ?: it.toString() })
            }
            // Companion keeps camera settings and the glasses are shared: put them back
            if (restoreCamera.isNotEmpty()) {
                restored = withTimeoutOrNull(3000) { runCatching { client.setCamera(restoreCamera) }.isSuccess } == true
            }
            when (result) {
                null -> "Companion didn't answer"
                OK -> null
                else -> result
            }
        }
        val fields = listOfNotNull("status" to "recording_stop", "recording_id" to recordingId, error?.let { "error" to it })
        log?.event("neon", fields = fields.toTypedArray())
        restored?.let { log?.event("neon", fields = arrayOf("status" to "scene_camera_restored", "ok" to it)) }
        scope.cancel()
    }

    /** Logs `disconnected` / `connected` whenever Companion, the glasses, their gaze or scene
     *  stream, or the recording drop out or return. */
    private suspend fun watch(everyMs: Long) {
        var problem: String? = null
        while (scope.isActive) {
            delay(everyMs)
            val now = try {
                val s = client.status()
                when {
                    !s.glassesConnected -> "glasses"
                    !s.recording -> "recording_stopped"
                    s.streams["gaze"] == false -> "gaze_stream"
                    s.streams["world"] == false -> "scene_stream"
                    else -> null
                }
            } catch (e: IOException) {
                "companion"
            }
            if (now != problem) {
                val log = log ?: return
                if (now != null) log.event("neon", fields = arrayOf("status" to "disconnected", "reason" to now, "recording_id" to recordingId))
                else log.event("neon", fields = arrayOf("status" to "connected", "recording_id" to recordingId))
                problem = now
            }
        }
    }

    companion object {
        const val CALIBRATION_FILE = "neon_calibration.bin"

        /**
         * Applies what [preflight] found to change (scene camera exposure, template answers), fetches
         * the glasses' calibration and starts a recording. `checklist`: each item and whether the
         * researcher confirmed it. Call off the main thread.
         */
        fun start(client: NeonClient, preflight: Preflight, checklist: List<Pair<String, Boolean>>): NeonLink {
            if (!preflight.ready) throw NeonNotReady(preflight.problems.joinToString("\n"))
            val status = try { // Companion may have changed since the check
                client.status()
            } catch (e: IOException) {
                throw NeonNotReady("Neon Companion isn't answering. Open the Neon Companion app on this phone and try again.")
            }
            if (!status.glassesConnected) throw NeonNotReady("The Neon glasses aren't connected. Plug them into this phone and wait for Companion to show them.")
            if (status.recording) throw NeonNotReady("Neon Companion is already recording. Stop that recording in Companion first, so this session gets its own.")
            var restore = emptyMap<String, String>()
            if (preflight.exposureChange.isNotEmpty()) {
                try {
                    client.setCamera(preflight.exposureChange)
                } catch (e: IOException) {
                    throw NeonNotReady("Couldn't set the scene camera exposure: ${e.message}")
                }
                restore = NeonSetup.restoreValues(preflight.exposureChange, preflight.camera.orEmpty())
            }
            val warnings = preflight.warnings.toMutableList()
            if (preflight.templateAnswers.isNotEmpty()) {
                runCatching { client.fillTemplate(preflight.templateAnswers) }
                    .onFailure { warnings += "Couldn't fill Companion's template: ${it.message}" }
            }
            val calibration = runCatching { client.calibration() }
                .onFailure { warnings += "Couldn't fetch the glasses' calibration: ${it.message}" }.getOrNull()
            val t = Clocks.elapsedNs()
            val id = try {
                client.startRecording()
            } catch (e: IOException) {
                if (restore.isNotEmpty()) runCatching { client.setCamera(restore) }
                throw NeonNotReady("Neon Companion couldn't start a recording: ${e.message}")
            }
            return NeonLink(client, id, preflight.copy(status = status, warnings = warnings), checklist, calibration, restore, t)
        }

        private const val OK = "ok"

        private fun unixNs(): Long = Instant.now().let { it.epochSecond * 1_000_000_000L + it.nano }
    }
}
