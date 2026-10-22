package org.socialeyes.pictogram.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonPrimitive
import org.socialeyes.pictogram.Session
import org.socialeyes.pictogram.log.ScreenRect
import org.socialeyes.pictogram.neon.CameraControl
import org.socialeyes.pictogram.neon.NeonSetup
import org.socialeyes.pictogram.study.Step
import kotlin.math.roundToInt

/** One scene camera setting of a settings_test step (auto, auto biased darker/brighter, or manual). */
internal data class TestExposure(val mode: String, val exposureUs: Int? = null, val autoBias: Double? = null) {
    val label: String
        get() = when {
            mode == "manual" -> "$exposureUs us"
            autoBias != null && autoBias != 0.0 -> "auto ${if (autoBias > 0) "+" else ""}${(autoBias * 100).roundToInt()}%"
            else -> "auto"
        }

    /** Companion's camera control values; auto always sets the AE brightness (back to `base`, or
     *  shifted from it towards the control's minimum or maximum by autoBias). */
    fun values(brightness: CameraControl?): Map<String, String> = when (mode) {
        "manual" -> mapOf("ae_mode" to "manual", "man_exp" to exposureUs.toString())
        else -> buildMap {
            put("ae_mode", "auto")
            val base = brightness?.current?.toIntOrNull() ?: return@buildMap
            val bias = autoBias ?: 0.0
            val lo = brightness.min
            val hi = brightness.max
            val target = when {
                bias < 0 && lo != null -> base + bias * (base - lo)
                bias > 0 && hi != null -> base + bias * (hi - base)
                else -> base.toDouble()
            }
            put("brightness", target.roundToInt().toString())
        }
    }
}

/** One setting: a screen brightness and a scene camera exposure. */
internal data class TestSetting(val brightness: Double, val exposure: TestExposure) {
    val label: String get() = "brightness %.2f, %s".format(brightness, exposure.label)
}

internal fun testSettings(step: Step): List<TestSetting> {
    val levels = step.doubles("brightness")?.takeIf { it.isNotEmpty() } ?: listOf(0.30, 0.45, 0.60)
    val exposures = (step.raw["exposures"] as? JsonArray)?.mapNotNull { e ->
        val o = e as? JsonObject ?: return@mapNotNull null
        TestExposure(o["mode"]?.jsonPrimitive?.contentOrNull ?: return@mapNotNull null,
            o["exposure_us"]?.jsonPrimitive?.intOrNull, o["auto_bias"]?.jsonPrimitive?.doubleOrNull)
    }?.takeIf { it.isNotEmpty() } ?: listOf(
        TestExposure("auto"), TestExposure("auto", autoBias = -0.5), TestExposure("manual", 1000), TestExposure("manual", 2000),
    )
    return levels.flatMap { b -> exposures.map { TestSetting(b, it) } }
}

private val SETTINGS_HOLDS = listOf(
    "Hold the phone the way you normally would.",
    "Hold the phone at arm's length: stretch your arm out fully.",
)

/** Auto exposure needs about a second to settle; the analysis skips that long after each change. */
private const val SETTLE_AUTO_MS = 1200
private const val SETTLE_MS = 300

/**
 * `settings_test`: for each hold, the study's on-screen tags in the top bar and tab bar around a
 * post photo while the app steps through screen brightness x Neon scene camera exposure itself,
 * `setting_s` seconds each (socialeyes.gaze.settings_test scores them). Logs `display_setting` and
 * a `marker_layout` (with `ladder`; the setting is the variant) for every setting, and puts the
 * brightness and scene camera back as they were when the step ends. Without the Neon it is skipped.
 */
@Composable
fun SettingsTestStep(session: Session, step: Step, onContinue: () -> Unit) {
    val neon = session.neon
    if (neon == null) {
        LaunchedEffect(Unit) {
            session.log.event("settings_test", fields = arrayOf("step_id" to step.id, "status" to "skipped", "reason" to "no_neon"))
        }
        MessageScreen("", "This step needs the Neon recording, which isn't running.", button = "Continue", onContinue = onContinue)
        return
    }
    // what the session had before this step, put back at its end (or if it's left early)
    val brightnessBefore = remember { session.brightness }
    var cameraBefore by remember { mutableStateOf<Map<String, CameraControl>?>(null) }
    var ready by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        cameraBefore = withContext(Dispatchers.IO) { neon.cameraState() }
        session.log.event("settings_test", fields = arrayOf("step_id" to step.id, "status" to "start",
            "camera_before" to cameraBefore?.mapValues { (_, c) -> mapOf("current" to c.current, "min" to c.min, "max" to c.max) }))
        ready = true
    }
    var restored by remember { mutableStateOf(false) }
    fun restore() {
        if (restored) return
        restored = true
        session.brightness = brightnessBefore
        val cam = cameraBefore ?: return
        Thread { runCatching { neon.setCamera(NeonSetup.restoreValues(cam), "settings_test") } }.start()
    }
    DisposableEffect(Unit) { onDispose { restore() } }
    if (!ready) return
    HoldSequence(session, step, SETTINGS_HOLDS, {
        restore()
        session.log.event("settings_test", fields = arrayOf("step_id" to step.id, "status" to "done"))
        onContinue()
    }) { hold, onDone -> SettingsScreen(session, step, hold, cameraBefore, onDone) }
}

@Composable
private fun SettingsScreen(session: Session, step: Step, hold: Int, cameraBefore: Map<String, CameraControl>?, onDone: () -> Unit) {
    val settings = remember { testSettings(step) }
    val settingS = step.double("setting_s") ?: 5.0
    val order = remember(hold) { barOrder(settings.size, step.int("rounds") ?: 2, hold) }
    var phase by remember { mutableIntStateOf(-1) }
    LaunchedEffect(Unit) {
        for (p in order.indices) {
            val s = settings[order[p]]
            val camera = s.exposure.values(cameraBefore?.get("brightness"))
            // the setting first, then the screen that logs it, so frames after the layout show it
            val error = withContext(Dispatchers.IO) {
                runCatching { session.neon?.setCamera(camera, "settings_test") }.exceptionOrNull()?.message
            }
            session.brightness = s.brightness.toFloat()
            session.log.event("display_setting", fields = arrayOf("step_id" to step.id, "brightness" to s.brightness,
                "camera" to camera, "source" to "settings_test", "variant" to s.label, "error" to error))
            phase = p
            delay((settingS * 1000).toLong())
        }
        onDone()
    }
    if (phase < 0) return
    val s = settings[order[phase]]
    key(phase) { SettingsLayout(session, step, hold, phase, s, s.exposure.values(cameraBefore?.get("brightness"))) }
}

@Composable
private fun SettingsLayout(session: Session, step: Step, hold: Int, phase: Int, s: TestSetting, camera: Map<String, String>) {
    val pkg = session.pkg
    val cfg = pkg.study.markers.onScreen
    val family = if (cfg.family in FAMILY_CELLS) cfg.family else "tag16h5"
    val ids = pkg.study.markers.screenTagIds
    val density = LocalDensity.current
    val view = LocalView.current
    val metrics = LocalContext.current.resources.displayMetrics
    val dark = isDarkTheme()
    val primary = MaterialTheme.colorScheme.onBackground
    fun Float.asDp(): Dp = with(density) { this@asDp.toDp() }

    val tags = rememberBarTags(family, ids, cfg.sizeMm, cfg.sideInsetMm, cfg.edgeGapMm)
    val sync = pkg.study.display.syncPatch
    val topStrip = if (sync.enabled) maxOf(24, sync.sizeDp + 16).dp else 0.dp
    val topBarH = maxOf(topStrip + 52.dp, tags.barPx.asDp())
    val tabBarH = maxOf(50.dp, tags.barPx.asDp())
    val clear = tags.clearPx.asDp()

    var origin by remember { mutableStateOf<Offset?>(null) }
    var boxPx by remember { mutableStateOf(Offset.Zero) }
    var imageRect by remember { mutableStateOf<ScreenRect?>(null) }
    var logged by remember { mutableStateOf(false) }

    // once per setting: a second layout pass moves nothing, but would start a new arrangement
    // (and a second settle time) in the analysis (21 Oct run: 95 layouts for 48 settings)
    LaunchedEffect(origin, imageRect) {
        val o = origin ?: return@LaunchedEffect
        val img = imageRect ?: return@LaunchedEffect
        if (boxPx == Offset.Zero || logged) return@LaunchedEffect
        logged = true
        session.log.event(
            "marker_layout",
            fields = arrayOf(
                "step_id" to step.id,
                "tags" to ids.withIndex().associate { (k, id) -> id.toString() to tags.rect(k, boxPx).offset(o.x, o.y).toJson() },
                "ladder" to mapOf(
                    "hold" to hold, "phase" to phase,
                    "screen" to ScreenRect(o.x, o.y, o.x + boxPx.x, o.y + boxPx.y).toJson(),
                    "tags" to ids.withIndex().associate { (k, id) ->
                        id.toString() to mapOf(
                            "kind" to "bars", "value_mm" to cfg.sizeMm, "size_mm" to cfg.sizeMm, "family" to family,
                            "cells" to tags.cells, "grey" to 0.0, "variant" to s.label, "corner" to listOf("top_left", "top_right", "bottom_right", "bottom_left")[k],
                        )
                    },
                    "bars" to mapOf(
                        "variant" to s.label, "top_bar_dp" to topBarH.value, "tab_bar_dp" to tabBarH.value,
                        "settings_test" to true, "brightness" to s.brightness, "camera" to camera,
                        "settle_ms" to if (s.exposure.mode == "auto") SETTLE_AUTO_MS else SETTLE_MS,
                        "image" to img.toJson(),
                    ),
                ),
            ),
        )
    }

    // a filler post's photo (what the brightness must not blow out), as in display_calibration
    val photo = remember {
        val post = session.plan.feed.lastOrNull { it.role == "filler" } ?: session.plan.feed.lastOrNull()
        post?.let { pkg.manifest.images[it.imageId] }?.let { pkg.file(it.file) }
    }

    Box(
        Modifier
            .fillMaxSize()
            .onGloballyPositioned { c ->
                val loc = IntArray(2).also(view::getLocationOnScreen)
                origin = c.positionInWindow() + Offset(loc[0].toFloat(), loc[1].toFloat())
                boxPx = Offset(c.size.width.toFloat(), c.size.height.toFloat())
            },
    ) {
        Column(Modifier.fillMaxSize()) {
            Column(Modifier.fillMaxWidth().height(topBarH)) {
                Spacer(Modifier.weight(1f))
                Row(
                    Modifier.fillMaxWidth().height(52.dp).padding(start = maxOf(14.dp, clear), end = maxOf(6.dp, clear)),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    FittedWordmark(pkg.study.platform.name, primary, Modifier.weight(1f))
                    BarIcon(FeedIcons.Heart)
                    BarIcon(FeedIcons.Messages)
                }
            }
            Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                photo?.let { file ->
                    val bitmap by rememberImage(file, metrics.widthPixels)
                    bitmap?.let {
                        Image(
                            it, null, contentScale = ContentScale.FillBounds,
                            modifier = Modifier.fillMaxWidth().aspectRatio(it.width.toFloat() / it.height).onGloballyPositioned { c ->
                                val loc = IntArray(2).also(view::getLocationOnScreen)
                                val p = c.positionInWindow()
                                imageRect = ScreenRect(p.x, p.y, p.x + c.size.width, p.y + c.size.height)
                                    .offset(loc[0].toFloat(), loc[1].toFloat())
                            },
                        )
                    }
                }
            }
            HorizontalDivider(thickness = 0.5.dp, color = FeedColors.divider(dark))
            Row(
                Modifier.fillMaxWidth().height(tabBarH).padding(horizontal = clear),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                listOf(FeedIcons.HomeFilled, FeedIcons.Search, FeedIcons.Create, FeedIcons.Reels).forEach {
                    Box(Modifier.weight(1f), contentAlignment = Alignment.Center) {
                        Icon(it, null, tint = primary, modifier = Modifier.size(26.dp))
                    }
                }
                Box(Modifier.weight(1f), contentAlignment = Alignment.Center) { ParticipantAvatar(27.dp, dark) }
            }
        }
        BarTagImages(pkg, tags, boxPx)
    }
}
