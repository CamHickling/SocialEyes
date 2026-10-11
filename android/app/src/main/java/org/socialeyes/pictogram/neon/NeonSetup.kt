package org.socialeyes.pictogram.neon

import org.socialeyes.pictogram.study.Neon
import org.socialeyes.pictogram.study.SceneExposure
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** The glasses' scene camera calibration (calibration.bin, as in a native Neon recording). */
data class SceneCalibration(val serial: String, val cameraMatrix: DoubleArray, val distortion: DoubleArray) {
    val fx get() = cameraMatrix[0]
    val fy get() = cameraMatrix[4]
    val cx get() = cameraMatrix[2]
    val cy get() = cameraMatrix[5]

    companion object {
        /** version (1 byte), serial (6 bytes), then the scene camera matrix (3x3) and 8 distortion
         *  coefficients as little-endian doubles (socialeyes.gaze.neon reads the same layout). */
        fun parse(bytes: ByteArray): SceneCalibration {
            require(bytes.size >= 7 + 17 * 8) { "calibration.bin is too short (${bytes.size} bytes)" }
            val buf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
            val serial = String(bytes, 1, 6, Charsets.US_ASCII).trimEnd('\u0000')
            buf.position(7)
            val k = DoubleArray(9) { buf.double }
            val d = DoubleArray(8) { buf.double }
            require(k[0] > 0 && k[4] > 0 && k[8] == 1.0) { "calibration.bin has no valid camera matrix" }
            return SceneCalibration(serial, k, d)
        }
    }
}

/** What the researcher sees before the recording starts, and what will be changed. */
data class Preflight(
    val status: NeonStatus,
    /** Scene camera controls now (null if Companion didn't answer). */
    val camera: Map<String, CameraControl>?,
    /** Camera settings the study asks for (empty: leave as is). */
    val exposureChange: Map<String, String>,
    /** Template answers to send, item id -> values, and the template titles they fill. */
    val templateAnswers: Map<String, List<String>>,
    val templateFilled: List<String>,
    /** Stop the session from starting until fixed. */
    val problems: List<String>,
    /** Worth knowing; the researcher may go on. */
    val warnings: List<String>,
) {
    val ready get() = problems.isEmpty()
}

object NeonSetup {

    /** Camera control values for the study's scene_exposure (Companion's names). */
    fun exposureValues(e: SceneExposure): Map<String, String> = buildMap {
        put("ae_mode", e.mode)
        e.exposureUs?.let { put("man_exp", it.toString()) }
        e.gain?.let { put("gain", it.toString()) }
        e.brightness?.let { put("brightness", it.toString()) }
    }

    /** The values that differ from the camera's current state; values outside Companion's allowed
     *  ranges are returned as problems. */
    fun exposureChange(wanted: Map<String, String>, now: Map<String, CameraControl>): Pair<Map<String, String>, List<String>> {
        val problems = mutableListOf<String>()
        val change = wanted.filter { (name, value) ->
            val c = now[name]
            if (c == null) {
                problems += "Companion doesn't offer camera control $name"
                false
            } else {
                c.reject(value)?.let { problems += "Scene exposure: $it" }
                c.current != value
            }
        }
        return change to problems
    }

    /** The camera values that put Companion back as it was before the session (its settings outlast
     *  the session, and the glasses are shared): the auto exposure mode and brightness, and the
     *  manual exposure time and gain only if it was in manual mode (in auto they're the camera's own). */
    fun restoreValues(before: Map<String, CameraControl>): Map<String, String> = buildMap {
        val mode = before["ae_mode"]?.current
        mode?.let { put("ae_mode", it) }
        before["brightness"]?.let { put("brightness", it.current) }
        if (mode == "manual") {
            before["man_exp"]?.let { put("man_exp", it.current) }
            before["gain"]?.let { put("gain", it.current) }
        }
    }

    /** Template answers from the study's title -> value map (titles match case-insensitively);
     *  returns answers by item id, the titles filled, and the study titles the template lacks. */
    fun templateAnswers(items: List<TemplateItem>, wanted: Map<String, String>, values: Map<String, String>):
        Triple<Map<String, List<String>>, List<String>, List<String>> {
        val byTitle = items.associateBy { it.title.trim().lowercase() }
        val answers = mutableMapOf<String, List<String>>()
        val filled = mutableListOf<String>()
        val missing = mutableListOf<String>()
        wanted.forEach { (title, pattern) ->
            val item = byTitle[title.trim().lowercase()]
            if (item == null) missing += title else {
                answers[item.id] = listOf(fill(pattern, values))
                filled += item.title
            }
        }
        return Triple(answers, filled, missing)
    }

    /** "{participant_id}" etc. replaced by `values`. */
    fun fill(pattern: String, values: Map<String, String>): String =
        Regex("\\{(\\w+)\\}").replace(pattern) { m -> values[m.groupValues[1]] ?: m.value }

    /** Everything the researcher should know before the recording starts. Blocks; call off the main thread. */
    fun check(client: NeonClient, neon: Neon, values: Map<String, String>): Preflight {
        val status = try {
            client.status()
        } catch (e: java.io.IOException) {
            throw NeonNotReady("Neon Companion isn't answering. Open the Neon Companion app on this phone and try again.")
        }
        val problems = mutableListOf<String>()
        val warnings = mutableListOf<String>()
        if (!status.glassesConnected) problems += "The Neon glasses aren't connected. Plug them into this phone and wait for Companion to show them."
        if (status.recording) problems += "Neon Companion is already recording. Stop that recording in Companion first, so this session gets its own."
        when (status.memoryState) {
            "CRITICAL" -> problems += "The phone is almost out of storage: free some space before recording."
            "LOW" -> warnings += "The phone's storage is low."
        }
        when (status.batteryState) {
            "CRITICAL" -> problems += "The phone's battery is critically low (${status.batteryLevel ?: "?"}%): charge it first."
            "LOW" -> warnings += "The phone's battery is low (${status.batteryLevel ?: "?"}%)."
        }
        if (status.glassesConnected) {
            listOf("gaze" to "gaze", "world" to "scene video").forEach { (stream, label) ->
                if (status.streams[stream] == false) warnings += "Companion reports no $label stream yet."
            }
        }

        val camera = runCatching { client.cameraState() }.getOrNull()
        var change = emptyMap<String, String>()
        neon.sceneExposure?.let { e ->
            if (camera == null) {
                problems += "The study sets the scene camera exposure, but Companion didn't report its camera settings " +
                    "(update Companion, or check the glasses' scene camera)."
            } else {
                val (c, p) = exposureChange(exposureValues(e), camera)
                change = c
                problems += p
            }
        }

        var answers = emptyMap<String, List<String>>()
        var filled = emptyList<String>()
        if (neon.template.isNotEmpty()) {
            val items = runCatching { client.templateItems() }.getOrNull()
            if (items == null) warnings += "Couldn't read Companion's recording template; fill it in by hand."
            else {
                val (a, f, missing) = templateAnswers(items, neon.template, values)
                answers = a
                filled = f
                if (missing.isNotEmpty()) warnings += "Companion's template has no field ${missing.joinToString { "\"$it\"" }}; " +
                    "those values won't be filled in."
            }
        }
        return Preflight(status, camera, change, answers, filled, problems, warnings)
    }
}
