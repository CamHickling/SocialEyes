package org.socialeyes.pictogram.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import org.socialeyes.pictogram.Session
import org.socialeyes.pictogram.log.ScreenRect
import org.socialeyes.pictogram.study.Step

/** Centered text with an optional button; used for instructions, end and placeholder screens. */
@Composable
fun MessageScreen(
    title: String,
    text: String,
    button: String?,
    minTimeS: Double = 0.0,
    onContinue: () -> Unit,
) {
    var enabled by remember { mutableStateOf(minTimeS <= 0) }
    LaunchedEffect(Unit) {
        delay((minTimeS * 1000).toLong())
        enabled = true
    }
    Column(
        Modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        if (title.isNotBlank()) {
            Text(title, fontSize = 24.sp, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.Center)
            Spacer(Modifier.height(16.dp))
        }
        Text(text, fontSize = 18.sp, textAlign = TextAlign.Center)
        if (button != null) {
            Spacer(Modifier.height(32.dp))
            Button(onClick = onContinue, enabled = enabled) { Text(button) }
        }
    }
}

/** Step types the app can't show yet. The step is still logged, so the session stays complete. */
@Composable
fun PlaceholderStep(step: Step, onContinue: () -> Unit) = MessageScreen(
    title = "Not available yet",
    text = "Step '${step.id}' (${step.type}) isn't supported by this version of the app.",
    button = "Skip",
    onContinue = onContinue,
)

/**
 * Screen AprilTags in the four corners (TL, TR, BR, BL, as `markers.screen_tag_ids`)
 * around a large patch that flashes with the sync code. The tags' screen
 * rectangles are logged in a `marker_layout` event. Continues by itself after `duration_s`.
 */
@Composable
fun MarkerCalibrationStep(session: Session, step: Step, onContinue: () -> Unit) {
    val pkg = session.pkg
    val view = LocalView.current
    val ids = pkg.study.markers.screenTagIds
    val rects = remember { HashMap<Int, ScreenRect>() }

    LaunchedEffect(Unit) {
        delay(((step.double("duration_s") ?: 4.0) * 1000).toLong())
        session.log.event(
            "marker_layout",
            fields = arrayOf("step_id" to step.id, "tags" to rects.mapKeys { it.key.toString() }.mapValues { it.value.toJson() }),
        )
        onContinue()
    }

    BoxWithConstraints(Modifier.fillMaxSize().background(Color.White)) {
        val tagSize = minOf(maxWidth, maxHeight) * 0.28f
        val corners = listOf(Alignment.TopStart, Alignment.TopEnd, Alignment.BottomEnd, Alignment.BottomStart)
        ids.zip(corners).forEach { (id, corner) ->
            val file = pkg.manifest.screenTags[id.toString()]?.let(pkg::file) ?: return@forEach
            val bitmap by rememberImage(file, 0)
            Box(
                Modifier
                    .align(corner)
                    .padding(12.dp)
                    .size(tagSize)
                    .onGloballyPositioned { c ->
                        val loc = IntArray(2).also(view::getLocationOnScreen)
                        val p = c.positionInWindow()
                        rects[id] = ScreenRect(p.x, p.y, p.x + c.size.width, p.y + c.size.height)
                            .offset(loc[0].toFloat(), loc[1].toFloat())
                    },
            ) {
                bitmap?.let {
                    Image(it, "tag $id", Modifier.fillMaxSize(), contentScale = ContentScale.Fit, filterQuality = FilterQuality.None)
                }
            }
        }
        Box(
            Modifier
                .align(Alignment.Center)
                .size(tagSize)
                .background(if (session.syncLevel == 1) Color.White else Color.Black),
        )
    }
}

/**
 * Gaze validation: dots at the study's normalised positions, one at a time;
 * the participant looks at each and taps it. Logs `validation_target` and `validation_tap`.
 */
@Composable
fun ValidationStep(session: Session, step: Step, onContinue: () -> Unit) {
    val points = session.pkg.manifest.validationPoints[step.id].orEmpty()
    var started by remember { mutableStateOf(false) }
    if (!started) {
        MessageScreen("", step.str("instructions") ?: "Look at each dot and tap it.", button = "Start") { started = true }
        return
    }
    if (points.isEmpty()) {
        LaunchedEffect(Unit) { onContinue() }
        return
    }

    val view = LocalView.current
    val targetPx = with(LocalDensity.current) { (step.int("target_dp") ?: 28).dp.toPx() }
    var index by remember { mutableIntStateOf(0) }
    var origin by remember { mutableStateOf(Offset.Zero) } // the box's top-left on screen
    var boxSize by remember { mutableStateOf(Offset.Zero) }

    fun target(i: Int) = Offset(points[i][0].toFloat() * boxSize.x, points[i][1].toFloat() * boxSize.y)

    if (boxSize != Offset.Zero) {
        LaunchedEffect(index) {
            val c = target(index) + origin
            session.log.event(
                "validation_target",
                fields = arrayOf("step_id" to step.id, "index" to index, "x_px" to c.x, "y_px" to c.y),
            )
        }
    }

    Canvas(
        Modifier
            .fillMaxSize()
            .onGloballyPositioned { c ->
                val loc = IntArray(2).also(view::getLocationOnScreen)
                origin = c.positionInWindow() + Offset(loc[0].toFloat(), loc[1].toFloat())
                boxSize = Offset(c.size.width.toFloat(), c.size.height.toFloat())
            }
            .pointerInput(Unit) {
                detectTapGestures { tap ->
                    if (index >= points.size) return@detectTapGestures
                    val p = tap + origin
                    session.log.event(
                        "validation_tap",
                        fields = arrayOf("step_id" to step.id, "index" to index, "x_px" to p.x, "y_px" to p.y),
                    )
                    if (index + 1 < points.size) index++ else {
                        index = points.size
                        onContinue()
                    }
                }
            },
    ) {
        if (boxSize == Offset.Zero || index >= points.size) return@Canvas
        val c = target(index)
        drawCircle(Color.Black, radius = targetPx / 2, center = c)
        drawCircle(Color.White, radius = targetPx / 8, center = c)
    }
}
