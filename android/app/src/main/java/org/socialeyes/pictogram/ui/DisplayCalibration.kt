package org.socialeyes.pictogram.ui

import android.os.Handler
import android.os.Looper
import android.provider.Settings
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.putJsonObject
import org.socialeyes.pictogram.Session
import org.socialeyes.pictogram.log.ScreenRect
import org.socialeyes.pictogram.neon.CameraControl
import org.socialeyes.pictogram.neon.ControlRequest
import org.socialeyes.pictogram.neon.ControlServer
import org.socialeyes.pictogram.neon.NeonSetup
import org.socialeyes.pictogram.study.Step
import java.io.File
import java.time.Instant
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * `display_calibration`: the session's on-screen tags around a post image, while a laptop
 * (`socialeyes calibrate-display <phone ip>`) steps through screen brightness x Neon scene camera
 * exposure and watches Companion's scene video, then sends the best setting back. The app keeps it
 * for the rest of the session (Session.brightness; the scene camera is put back by NeonLink at the
 * end). The laptop talks to a [ControlServer] on `port`:
 *   GET  /state  layout (tags, image, screen), brightness, scene camera, calibration
 *   POST /apply  {brightness, camera}: set both now; answers applied_unix_ns
 *   POST /done   {brightness, camera, summary}: keep these (null: what the session had before)
 * Logs `display_setting` for every change and `display_calibration` at the end; the laptop's
 * results go to display_calibration_<step id>.json in the session folder.
 */
@Composable
fun DisplayCalibrationStep(session: Session, step: Step, onContinue: () -> Unit) {
    val neon = session.neon
    val port = step.int("port") ?: 8091
    val waitS = step.double("wait_s") ?: 60.0
    val context = LocalContext.current
    val view = LocalView.current
    var status by remember { mutableStateOf("Waiting for the laptop") }
    var finished by remember { mutableStateOf(false) }
    var showSkip by remember { mutableStateOf(false) }
    var imageRect by remember { mutableStateOf<ScreenRect?>(null) }
    val main = remember { Handler(Looper.getMainLooper()) }
    // what the session had before this step, put back on skip or failure
    val before = remember { Before(session.brightness) }

    fun finish(result: String, fields: Array<Pair<String, Any?>>) {
        if (finished) return
        finished = true
        session.log.event("display_calibration", fields = arrayOf("step_id" to step.id, "status" to result, *fields))
        main.post { status = if (result == "done") "Done" else "Skipped" }
        main.postDelayed({ onContinue() }, if (result == "done") 1200 else 300)
    }

    fun restoreBefore(): Boolean {
        main.post { session.brightness = before.brightness }
        val cam = before.camera ?: return true
        return if (before.cameraTouched) runCatching { neon?.setCamera(NeonSetup.restoreValues(cam), "display_calibration") }.isSuccess else true
    }

    fun apply(brightness: Float?, camera: Map<String, String>, source: String): Long {
        val latch = CountDownLatch(1)
        main.post {
            if (brightness != null) session.brightness = brightness
            latch.countDown()
        }
        latch.await(2, TimeUnit.SECONDS)
        if (camera.isNotEmpty()) {
            val n = neon ?: error("no Neon recording in this session: the scene camera can't be set")
            before.cameraTouched = true
            n.setCamera(camera, source)
        }
        session.log.event("display_setting", fields = arrayOf("step_id" to step.id, "brightness" to brightness,
            "camera" to camera, "source" to source))
        return Instant.now().let { it.epochSecond * 1_000_000_000L + it.nano }
    }

    fun handle(req: ControlRequest): JsonObject {
        if (finished) error("the display calibration step has ended")
        main.post { showSkip = false; status = "Calibrating…" }
        return when (req.method to req.path) {
            "GET" to "/state" -> {
                if (before.camera == null) before.camera = neon?.cameraState()
                state(session, step, imageRect, before.camera, context)
            }
            "POST" to "/apply" -> {
                val b = req.body ?: JsonObject(emptyMap())
                val brightness = (b["brightness"] as? JsonPrimitive)?.doubleOrNull?.toFloat()
                val camera = strings(b["camera"] as? JsonObject)
                val t = apply(brightness, camera, "display_calibration")
                main.post { status = "Calibrating… " + listOfNotNull(brightness?.let { "brightness %.2f".format(it) },
                    camera["man_exp"]?.let { "exposure $it µs" } ?: camera["ae_mode"]?.let { "exposure $it" }).joinToString(", ") }
                buildJsonObject { put("applied_unix_ns", t) }
            }
            "POST" to "/done" -> {
                val b = req.body ?: JsonObject(emptyMap())
                (b["summary"] as? JsonObject)?.let { s ->
                    runCatching { File(session.log.dir, "display_calibration_${step.id}.json").writeText(s.toString()) }
                }
                val brightness = (b["brightness"] as? JsonPrimitive)?.doubleOrNull?.toFloat()
                val camera = strings(b["camera"] as? JsonObject)
                val best = (b["summary"] as? JsonObject)?.get("best") as? JsonObject
                fun num(k: String) = (best?.get(k) as? JsonPrimitive)?.doubleOrNull
                if (brightness == null) {
                    val ok = restoreBefore()
                    finish("failed", arrayOf("restored" to ok))
                } else {
                    apply(brightness, camera, "display_calibration_result")
                    finish("done", arrayOf("brightness" to brightness, "camera" to camera,
                        "tags_read" to num("tags_read"), "blown_out" to num("blown_out")))
                }
                buildJsonObject { put("ok", true) }
            }
            else -> error("unknown request ${req.method} ${req.path}")
        }
    }

    DisposableEffect(Unit) {
        if (neon == null) {
            finish("skipped", arrayOf("reason" to "no_neon"))
            return@DisposableEffect onDispose {}
        }
        val server = ControlServer(port, ::handle)
        val started = runCatching { server.start() }
        started.onFailure { e ->
            status = "Couldn't open port $port: ${e.message}"
            showSkip = true
        }
        onDispose { server.stop() }
    }
    LaunchedEffect(Unit) {
        delay((waitS * 1000).toLong())
        if (!finished) showSkip = true
    }

    val image = remember {
        val post = session.plan.feed.lastOrNull { it.role == "filler" } ?: session.plan.feed.lastOrNull()
        post?.let { session.pkg.manifest.images[it.imageId] }?.let { session.pkg.file(it.file) }
    }
    val addresses = remember { ControlServer.localAddresses() }

    Column(
        Modifier.fillMaxSize().padding(horizontal = 24.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(step.str("text").orEmpty(), fontSize = 18.sp, textAlign = TextAlign.Center)
        image?.let { file ->
            val bitmap by rememberImage(file, 1080)
            bitmap?.let {
                Image(
                    it, null, contentScale = ContentScale.FillBounds,
                    modifier = Modifier.fillMaxWidth().aspectRatio(it.width.toFloat() / it.height).onGloballyPositioned { c ->
                        val loc = IntArray(2).also(view::getLocationOnScreen)
                        val p = c.positionInWindow()
                        imageRect = ScreenRect(p.x, p.y, p.x + c.size.width, p.y + c.size.height).offset(loc[0].toFloat(), loc[1].toFloat())
                    },
                )
            }
        }
        // the participant sees only the instruction; the phone's address is on the researcher's
        // eye tracker check screen, and again here next to Skip
        if (status == "Done") Text("Done", fontSize = 14.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (showSkip && !finished) {
            if (addresses.isNotEmpty() || status.startsWith("Couldn't")) {
                Text(if (status.startsWith("Couldn't")) status else "Laptop: socialeyes calibrate-display ${addresses.first()}",
                    fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center)
            }
            TextButton(onClick = {
                Thread {
                    val ok = restoreBefore()
                    finish("skipped", arrayOf("reason" to "researcher", "restored" to ok))
                }.start()
            }) { Text("Skip calibration") }
        }
    }
}

private class Before(val brightness: Float?) {
    @Volatile var camera: Map<String, CameraControl>? = null
    @Volatile var cameraTouched = false
}

private fun strings(o: JsonObject?): Map<String, String> =
    o?.mapNotNull { (k, v) -> (v as? JsonPrimitive)?.contentOrNull?.let { k to it } }?.toMap().orEmpty()

private fun state(session: Session, step: Step, image: ScreenRect?, camera: Map<String, CameraControl>?,
                  context: android.content.Context): JsonObject {
    val dm = android.util.DisplayMetrics().also {
        @Suppress("DEPRECATION")
        (context as? android.app.Activity)?.windowManager?.defaultDisplay?.getRealMetrics(it)
            ?: it.setTo(context.resources.displayMetrics)
    }
    val system = runCatching { Settings.System.getInt(context.contentResolver, Settings.System.SCREEN_BRIGHTNESS) / 255.0 }.getOrNull()
    val calib = session.neon?.sceneCalibration
    return buildJsonObject {
        put("session_uid", session.log.dir.name)
        put("step_id", step.id)
        putJsonObject("screen") {
            put("width_px", dm.widthPixels); put("height_px", dm.heightPixels)
            put("xdpi", dm.xdpi); put("ydpi", dm.ydpi)
        }
        putJsonObject("tags") { session.screenTagRects.forEach { (id, r) -> put(id.toString(), r.toJson()) } }
        image?.let { put("image", it.toJson()) }
        session.brightness?.let { put("brightness", it) }
        system?.let { put("system_brightness", it) }
        camera?.let { cam ->
            putJsonObject("camera") {
                cam.forEach { (k, c) ->
                    putJsonObject(k) {
                        put("current", c.current.toIntOrNull()?.let(::JsonPrimitive) ?: JsonPrimitive(c.current))
                        c.min?.let { put("min", it) }
                        c.max?.let { put("max", it) }
                        if (c.allowed.isNotEmpty()) put("allowed", JsonArray(c.allowed.map(::JsonPrimitive)))
                    }
                }
            }
        }
        calib?.let { c ->
            putJsonObject("calibration") {
                putJsonArray("K") { c.cameraMatrix.forEach { add(JsonPrimitive(it)) } }
                putJsonArray("dist") { c.distortion.forEach { add(JsonPrimitive(it)) } }
            }
        }
    }
}
