package org.socialeyes.pictogram.ui

import android.os.Build
import android.view.RoundedCorner
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import org.socialeyes.pictogram.Session
import org.socialeyes.pictogram.log.Clocks
import org.socialeyes.pictogram.log.ScreenRect
import org.socialeyes.pictogram.study.SyncPatchConfig
import kotlin.math.ceil
import kotlin.math.roundToInt

/** Runs the procedure, one step at a time, with the sync patch on top. */
@Composable
fun SessionScreen(session: Session, onExit: () -> Unit) {
    val pkg = session.pkg
    StudyTheme(dark = pkg.study.platform.theme == "dark") {
        var confirmAbort by remember { mutableStateOf(false) }
        BackHandler { if (session.log.finished) onExit() else confirmAbort = true }

        Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
            val step = session.currentStep
            key(session.stepIndex) {
                when (step?.type) {
                    null -> MessageScreen("", "Thank you!", button = null) {}
                    "instructions" -> MessageScreen(
                        title = step.str("title").orEmpty(),
                        text = step.str("text").orEmpty(),
                        button = step.str("button") ?: "Continue",
                        minTimeS = step.double("min_time_s") ?: 0.0,
                    ) { session.next() }
                    "feed" -> FeedScreen(session, step) { reason -> session.next(reason) }
                    "marker_calibration" -> MarkerCalibrationStep(session, step) { session.next() }
                    "validation" -> ValidationStep(session, step) { session.next() }
                    "questionnaire" -> QuestionnaireStep(session, step) { session.next() }
                    "image_rating" -> ImageRatingStep(session, step) { session.next() }
                    "recognition" -> RecognitionStep(session, step) { session.next() }
                    "end" -> MessageScreen("", step.str("text").orEmpty(), button = null) {}
                    else -> PlaceholderStep(step) { session.next() }
                }
            }

            val sync = pkg.study.display.syncPatch
            if (sync.enabled) {
                SyncPatch(
                    session, sync,
                    Modifier.align(if (sync.corner == "top_right") Alignment.TopEnd else Alignment.TopStart),
                )
            }
            FrameMonitor(session)

            if (confirmAbort) {
                AlertDialog(
                    onDismissRequest = { confirmAbort = false },
                    title = { Text("Stop this session?") },
                    text = { Text("The data recorded so far is kept and marked as aborted.") },
                    confirmButton = {
                        TextButton(onClick = { session.abort(); onExit() }) { Text("Stop session") }
                    },
                    dismissButton = { TextButton(onClick = { confirmAbort = false }) { Text("Continue session") } },
                )
            }
        }
    }
}

@Composable
fun StudyTheme(dark: Boolean, content: @Composable () -> Unit) {
    val colors = if (dark) {
        darkColorScheme(background = Color.Black, surface = Color.Black)
    } else {
        lightColorScheme(background = Color.White, surface = Color.White, surfaceVariant = Color(0xFFEFEFEF))
    }
    MaterialTheme(colorScheme = colors, content = content)
}

/**
 * The flickering patch the eye tracker's scene camera sees. Its grey level
 * follows the study's sync code, one bit per `bit_ms`, counted from session
 * start. Every change is logged as a `sync_patch` event with the time of the
 * frame that shows it. Its screen rectangle goes into session.json (`sync_patch`).
 */
@Composable
private fun SyncPatch(session: Session, cfg: SyncPatchConfig, modifier: Modifier) {
    val code = session.pkg.manifest.syncCode
    val view = LocalView.current
    var inset by remember { mutableIntStateOf(0) }
    var loggedRect by remember { mutableStateOf<ScreenRect?>(null) }

    LaunchedEffect(Unit) {
        inset = roundedCornerInset(view, cfg.corner)
        val bitNs = code.bitMs * 1_000_000L
        while (true) withFrameNanos { frame ->
            val t = Clocks.fromMonotonic(frame)
            val k = ((t - session.startNs) / bitNs).coerceAtLeast(0)
            val level = code.bits[(k % code.bits.size).toInt()]
            if (level != session.syncLevel) {
                session.syncLevel = level
                session.log.event("sync_patch", t, "level" to level)
            }
        }
    }

    val grey = if (session.syncLevel == 1) cfg.high else cfg.low
    Box(
        modifier
            .offset { IntOffset(if (cfg.corner == "top_right") -inset else inset, inset) }
            .size(cfg.sizeDp.dp)
            .background(Color(grey, grey, grey))
            .onGloballyPositioned { c ->
                val loc = IntArray(2).also(view::getLocationOnScreen)
                val p = c.positionInWindow()
                val r = ScreenRect(p.x, p.y, p.x + c.size.width, p.y + c.size.height).offset(loc[0].toFloat(), loc[1].toFloat())
                if (r != loggedRect) {
                    loggedRect = r
                    session.log.setMeta("sync_patch", r.toJson())
                }
            },
    )
}

/** Moves the patch in from a rounded display corner so none of it is cut off. */
private fun roundedCornerInset(view: android.view.View, corner: String): Int {
    if (Build.VERSION.SDK_INT < 31) return 0
    val position = if (corner == "top_right") RoundedCorner.POSITION_TOP_RIGHT else RoundedCorner.POSITION_TOP_LEFT
    val rc = view.rootWindowInsets?.getRoundedCorner(position) ?: return 0
    // The square from (d, d) outwards lies inside the arc when d = r (1 - 1/sqrt 2).
    return ceil(rc.radius * 0.2929).toInt()
}

/**
 * Logs `jank` events: dropped frames, at most once per second. Also keeps a
 * frame callback running so animations and the sync patch never stall.
 */
@Composable
private fun FrameMonitor(session: Session) {
    val view = LocalView.current
    LaunchedEffect(Unit) {
        @Suppress("DEPRECATION")
        val refresh = view.display?.refreshRate?.takeIf { it > 0 } ?: 60f
        val periodNs = 1e9 / refresh
        var last = 0L
        var windowStart = 0L
        var dropped = 0
        var longestNs = 0L
        while (true) withFrameNanos { frame ->
            if (last > 0) {
                val dt = frame - last
                // Gaps over a second are the app being in the background, not jank.
                if (dt > 1.5 * periodNs && dt < 1_000_000_000L) {
                    dropped += (dt / periodNs).roundToInt() - 1
                    longestNs = maxOf(longestNs, dt)
                }
            } else {
                windowStart = frame
            }
            last = frame
            if (frame - windowStart >= 1_000_000_000L) {
                if (dropped > 0) {
                    session.log.event(
                        "jank", Clocks.fromMonotonic(frame),
                        "frames_dropped" to dropped, "longest_frame_ms" to Math.round(longestNs / 1e5) / 10.0,
                    )
                }
                windowStart = frame
                dropped = 0
                longestNs = 0
            }
        }
    }
}
