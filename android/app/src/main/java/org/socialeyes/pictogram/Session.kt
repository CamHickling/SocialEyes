package org.socialeyes.pictogram

import android.app.Activity
import android.os.Build
import android.util.DisplayMetrics
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.setValue
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.socialeyes.pictogram.log.Clocks
import org.socialeyes.pictogram.log.SessionLog
import org.socialeyes.pictogram.log.TouchRecorder
import org.socialeyes.pictogram.study.Plan
import org.socialeyes.pictogram.study.Step
import org.socialeyes.pictogram.study.StudyPackage
import org.socialeyes.pictogram.study.flag
import java.io.File
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter

/** One participant running through the procedure. Owns the session log. */
class Session(val pkg: StudyPackage, val plan: Plan, val log: SessionLog) {
    val steps: List<Step> = pkg.steps
    val startNs: Long = Clocks.elapsedNs()
    val touches = TouchRecorder(log) { currentStep?.id ?: "" }

    var stepIndex by mutableIntStateOf(0)
        private set

    val currentStep: Step? get() = steps.getOrNull(stepIndex)

    /** Current sync code bit (0/1), driven by the sync patch; -1 before the first frame. */
    var syncLevel by mutableIntStateOf(-1)

    fun begin() = startStep()

    /** Leaves the current step. `reason`: `continue`, `done_button` or `time_limit`. */
    fun next(reason: String = "continue") {
        val step = currentStep ?: return
        log.event("step_end", fields = arrayOf("step_id" to step.id, "reason" to reason))
        stepIndex++
        startStep()
    }

    fun abort() = log.finish("aborted")

    private fun startStep() {
        val step = currentStep
        if (step == null) {
            log.finish("completed") // procedure without an end step
            return
        }
        log.event("step_start", fields = arrayOf("step_id" to step.id, "step_type" to step.type))
        if (step.type == "end") log.finish("completed")
    }

    companion object {
        const val FORMAT_VERSION = 1

        fun dataRoot(activity: Activity) = File(activity.getExternalFilesDir(null), "data")

        fun hasData(activity: Activity, studyId: String, participantId: String) =
            File(dataRoot(activity), "$studyId/$participantId").list()?.isNotEmpty() == true

        fun create(activity: Activity, pkg: StudyPackage, participantId: String): Session {
            val plan = pkg.loadPlan(participantId)
            val now = OffsetDateTime.now()
            val uid = participantId + "-" + now.format(DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmss"))
            val dir = File(dataRoot(activity), "${pkg.study.id}/$participantId/$uid")
            check(dir.mkdirs()) { "could not create $dir" }

            val logging = effectiveLogging(pkg.study.logging)
            val meta = buildJsonObject {
                put("format", "socialeyes-session")
                put("format_version", FORMAT_VERSION)
                put("study_id", pkg.study.id)
                put("study_version", pkg.study.version)
                put("participant_id", participantId)
                put("session_uid", uid)
                put("app_version", BuildConfig.VERSION_NAME)
                put("started_wall", now.format(DateTimeFormatter.ISO_OFFSET_DATE_TIME))
                put("clock", Clocks.snapshot())
                put("device", deviceInfo(activity))
                put("logging", logging)
            }
            return Session(pkg, plan, SessionLog(dir, meta, logTouches = logging.flag("touches", true)))
        }

        /**
         * The study's `logging:` section with what this app version can't record yet
         * switched off, so session.json says what was actually recorded.
         */
        private fun effectiveLogging(requested: JsonObject): JsonObject {
            val out = LinkedHashMap(requested)
            out["sensors"] = SessionLog.toJson(false)
            out["screen_recording"] = SessionLog.toJson(false)
            out["front_camera"] = buildJsonObject { put("enabled", false) }
            return JsonObject(out)
        }

        @Suppress("DEPRECATION") // getRealMetrics/defaultDisplay: the replacements need API 30
        private fun deviceInfo(activity: Activity): JsonObject {
            val display = activity.windowManager.defaultDisplay
            val dm = DisplayMetrics().also { display.getRealMetrics(it) }
            return buildJsonObject {
                put("manufacturer", Build.MANUFACTURER)
                put("model", Build.MODEL)
                put("android_sdk", Build.VERSION.SDK_INT)
                put("screen_width_px", dm.widthPixels)
                put("screen_height_px", dm.heightPixels)
                put("density_dpi", dm.densityDpi)
                put("xdpi", dm.xdpi)
                put("ydpi", dm.ydpi)
                put("refresh_hz", display.refreshRate)
                put("font_scale", activity.resources.configuration.fontScale)
            }
        }
    }
}
