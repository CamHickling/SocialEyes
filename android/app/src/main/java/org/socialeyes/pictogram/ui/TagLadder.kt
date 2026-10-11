package org.socialeyes.pictogram.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.IntOffset
import kotlinx.coroutines.delay
import org.socialeyes.pictogram.Session
import org.socialeyes.pictogram.log.ScreenRect
import org.socialeyes.pictogram.study.Step
import kotlin.math.ceil
import kotlin.math.roundToInt

/** One tag on the ladder screen: what it tests and where its black square's centre is (mm). */
internal data class LadderTag(val id: Int, val kind: String, val valueMm: Double, val sizeMm: Double,
                              val cxMm: Double, val cyMm: Double)

/**
 * The ladder layout for a screen of wMm x hMm (black-square centres, mm from the top-left).
 * Four `sizes` down the middle; `reference`-size tags at the left and right edges, their black
 * border `insets` from the edge; two at the top and two at the bottom edge, `gaps` from it.
 * Odd phases reverse the order so no size or inset always sits at the same height.
 * Tag ids from `first`: sizes, left insets, right insets, top gaps, bottom gaps (4+4+4+2+2).
 */
internal fun ladderLayout(
    wMm: Double, hMm: Double, sizes: List<Double>, insets: List<Double>, gaps: List<Double>,
    reference: Double, first: Int, phase: Int,
): List<LadderTag> {
    val flip = phase % 2 == 1
    val fwd = listOf(0, 1, 2, 3)
    val rev = fwd.reversed()
    val zoneTop = 22.0
    val pitch = (hMm - 2 * zoneTop) / 4
    val rowY = { k: Int -> zoneTop + (k + 0.5) * pitch }
    val half = reference / 2
    return buildList {
        (if (flip) rev else fwd).forEachIndexed { k, i ->
            add(LadderTag(first + i, "size", sizes[i], sizes[i], wMm / 2, rowY(k)))
        }
        (if (flip) rev else fwd).forEachIndexed { k, i ->
            add(LadderTag(first + 4 + i, "left_inset", insets[i], reference, insets[i] + half, rowY(k)))
        }
        (if (flip) fwd else rev).forEachIndexed { k, i ->
            add(LadderTag(first + 8 + i, "right_inset", insets[i], reference, wMm - insets[i] - half, rowY(k)))
        }
        val (a, b) = if (flip) 1 to 0 else 0 to 1
        add(LadderTag(first + 12 + a, "top_gap", gaps[a], reference, wMm * 0.25, gaps[a] + half))
        add(LadderTag(first + 12 + b, "top_gap", gaps[b], reference, wMm * 0.75, gaps[b] + half))
        add(LadderTag(first + 14 + b, "bottom_gap", gaps[b], reference, wMm * 0.25, hMm - gaps[b] - half))
        add(LadderTag(first + 14 + a, "bottom_gap", gaps[a], reference, wMm * 0.75, hMm - gaps[a] - half))
    }
}

private val DEFAULT_HOLDS = listOf(
    "Hold the phone the way you normally would.",
    "Hold the phone a little further away, near arm's length.",
    "Rest the phone low, near your lap, and look down at it.",
)

/**
 * `tag_ladder`: for each hold (an instruction for how to hold the phone), a white screen of
 * tags in several sizes and edge clearances for `hold_s`, so a Neon recording shows which the
 * scene camera can read (socialeyes.gaze.ladder). Logs `tag_ladder_hold` start/end and a
 * `marker_layout` (with `ladder`) for every arrangement.
 */
@Composable
fun TagLadderStep(session: Session, step: Step, onContinue: () -> Unit) {
    val holds = step.strings("holds")?.takeIf { it.isNotEmpty() } ?: DEFAULT_HOLDS
    var hold by remember { mutableIntStateOf(0) }
    var running by remember { mutableStateOf(false) }
    if (hold >= holds.size) {
        LaunchedEffect(Unit) { onContinue() }
        return
    }
    if (!running) {
        MessageScreen("", "${holds[hold]}\n\nThen tap Start and keep looking at the screen until it changes.", button = "Start") {
            session.log.event("tag_ladder_hold", fields = arrayOf("step_id" to step.id, "hold" to hold, "status" to "start",
                "instruction" to holds[hold]))
            running = true
        }
        return
    }
    key(hold) {
        LadderScreen(session, step, hold) {
            session.log.event("tag_ladder_hold", fields = arrayOf("step_id" to step.id, "hold" to hold, "status" to "end"))
            running = false
            hold++
        }
    }
}

@Composable
private fun LadderScreen(session: Session, step: Step, hold: Int, onDone: () -> Unit) {
    val pkg = session.pkg
    val metrics = LocalContext.current.resources.displayMetrics
    val density = LocalDensity.current
    val view = LocalView.current
    val pxPerMmX = metrics.xdpi / 25.4
    val pxPerMmY = metrics.ydpi / 25.4
    val sizes = step.doubles("sizes_mm") ?: listOf(8.0, 10.0, 12.0, 14.0)
    val insets = step.doubles("side_insets_mm") ?: listOf(3.0, 4.0, 5.0, 6.0)
    val gaps = step.doubles("edge_gaps_mm") ?: listOf(1.5, 3.5)
    val reference = step.double("reference_mm") ?: 12.0
    val first = step.int("first_tag_id") ?: 20
    val holdS = step.double("hold_s") ?: 20.0
    val flipS = step.double("flip_every_s") ?: 5.0

    var phase by remember { mutableIntStateOf(0) }
    var origin by remember { mutableStateOf<Offset?>(null) } // the box's top-left on screen
    var boxPx by remember { mutableStateOf(Offset.Zero) }

    LaunchedEffect(Unit) {
        val phases = ceil(holdS / flipS).toInt().coerceAtLeast(1)
        for (p in 0 until phases) {
            phase = p
            delay((minOf(flipS, holdS - p * flipS) * 1000).toLong())
        }
        onDone()
    }

    // Whole-image rectangles (12 cells: the 8-cell tag in a 2-cell white margin), in box pixels.
    fun rect(t: LadderTag): ScreenRect {
        val w = (t.sizeMm * 1.5 * pxPerMmX).roundToInt()
        val h = (t.sizeMm * 1.5 * pxPerMmY).roundToInt()
        val l = (t.cxMm * pxPerMmX).roundToInt() - w / 2
        val top = (t.cyMm * pxPerMmY).roundToInt() - h / 2
        return ScreenRect(l.toFloat(), top.toFloat(), (l + w).toFloat(), (top + h).toFloat())
    }

    val tags = if (boxPx == Offset.Zero) emptyList() else
        ladderLayout(boxPx.x / pxPerMmX, boxPx.y / pxPerMmY, sizes, insets, gaps, reference, first, phase)

    LaunchedEffect(phase, origin) {
        val o = origin ?: return@LaunchedEffect
        if (tags.isEmpty()) return@LaunchedEffect
        session.log.event(
            "marker_layout",
            fields = arrayOf(
                "step_id" to step.id,
                "tags" to tags.associate { it.id.toString() to rect(it).offset(o.x, o.y).toJson() },
                "ladder" to mapOf(
                    "hold" to hold, "phase" to phase,
                    "screen" to ScreenRect(o.x, o.y, o.x + boxPx.x, o.y + boxPx.y).toJson(),
                    "tags" to tags.associate {
                        it.id.toString() to mapOf("kind" to it.kind, "value_mm" to it.valueMm, "size_mm" to it.sizeMm)
                    },
                ),
            ),
        )
    }

    Box(
        Modifier
            .fillMaxSize()
            .background(Color.White)
            .onGloballyPositioned { c ->
                val loc = IntArray(2).also(view::getLocationOnScreen)
                origin = c.positionInWindow() + Offset(loc[0].toFloat(), loc[1].toFloat())
                boxPx = Offset(c.size.width.toFloat(), c.size.height.toFloat())
            },
    ) {
        tags.forEach { t ->
            key(t.id) {
                val file = pkg.manifest.screenTags[t.id.toString()]?.let(pkg::file)
                val bitmap = file?.let { rememberImage(it, 0).value }
                val r = rect(t)
                Box(
                    Modifier
                        .offset { IntOffset(r.left.roundToInt(), r.top.roundToInt()) }
                        .size(with(density) { (r.right - r.left).toDp() }, with(density) { (r.bottom - r.top).toDp() }),
                ) {
                    bitmap?.let {
                        Image(it, "tag ${t.id}", Modifier.fillMaxSize(), contentScale = ContentScale.FillBounds,
                            filterQuality = FilterQuality.None)
                    }
                }
            }
        }
    }
}
