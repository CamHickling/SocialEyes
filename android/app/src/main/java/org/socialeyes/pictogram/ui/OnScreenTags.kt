package org.socialeyes.pictogram.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.requiredSize
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import kotlinx.coroutines.delay
import org.socialeyes.pictogram.Session
import org.socialeyes.pictogram.log.ScreenRect
import org.socialeyes.pictogram.study.Step

// The tag images are 12 cells: an 8-cell tag (black border included) in a 2-cell white margin.
private const val TAG_CELLS = 8f
private const val IMAGE_CELLS = 12f
private const val SHOWN_CELLS = 10f // keep a 1-cell quiet zone, the detector's minimum
private const val SIDE_INSET_MM = 6f // clear of rounded corners and curved screen edges
// Clear of the top and bottom screen edges: with only the 1-cell quiet zone there, the tag's
// border blurred into the dark bezel and the top tags were missed in most frames (CAM-165).
private const val EDGE_INSET_MM = 2f

/**
 * `markers.on_screen`: the four screen tags kept on screen for a whole step, two in a band
 * above it and two below (TL, TR, BR, BL, as `markers.screen_tag_ids`), so gaze can be put
 * on the screen without anything around the phone. The step gets the space in between.
 * The tags' rectangles (whole 12-cell images, like marker_calibration's) are logged once in
 * a `marker_layout` event with `on_screen: true`. A display_calibration step always gets them.
 */
@Composable
fun OnScreenTags(session: Session, step: Step, content: @Composable () -> Unit) {
    val pkg = session.pkg
    val cfg = pkg.study.markers.onScreen
    if (step.id !in cfg.steps && step.type != "display_calibration") {
        content()
        return
    }
    val metrics = LocalContext.current.resources.displayMetrics
    val density = LocalDensity.current
    val view = LocalView.current
    val tagPx = (cfg.sizeMm / 25.4 * metrics.xdpi).toFloat()
    val cell = tagPx / TAG_CELLS
    val shown = with(density) { (cell * SHOWN_CELLS).toDp() }
    val image = with(density) { (cell * IMAGE_CELLS).toDp() }
    val inset = with(density) { (SIDE_INSET_MM / 25.4f * metrics.xdpi - cell).coerceAtLeast(0f).toDp() }
    val edge = with(density) { (EDGE_INSET_MM / 25.4f * metrics.ydpi).toDp() }
    val ids = pkg.study.markers.screenTagIds
    val rects = remember { HashMap<Int, ScreenRect>() }

    LaunchedEffect(Unit) {
        while (rects.size < ids.size) delay(50)
        session.screenTagRects = rects.toMap()
        session.log.event(
            "marker_layout",
            fields = arrayOf(
                "step_id" to step.id,
                "on_screen" to true,
                "tags" to rects.mapKeys { it.key.toString() }.mapValues { it.value.toJson() },
            ),
        )
    }

    @Composable
    fun Tag(id: Int) {
        val file = pkg.manifest.screenTags[id.toString()]?.let(pkg::file) ?: return
        val bitmap by rememberImage(file, 0)
        Box(
            Modifier
                .size(shown)
                .clipToBounds()
                .onGloballyPositioned { c ->
                    val loc = IntArray(2).also(view::getLocationOnScreen)
                    val p = c.positionInWindow()
                    val margin = cell // the image overhangs the shown box by one cell on each side
                    rects[id] = ScreenRect(p.x - margin, p.y - margin, p.x + c.size.width + margin, p.y + c.size.height + margin)
                        .offset(loc[0].toFloat(), loc[1].toFloat())
                },
        ) {
            bitmap?.let {
                Image(it, "tag $id", Modifier.requiredSize(image), contentScale = ContentScale.FillBounds,
                    filterQuality = FilterQuality.None)
            }
        }
    }

    @Composable
    fun Band(left: Int, right: Int, top: Boolean) {
        val pad = if (top) Modifier.padding(top = edge) else Modifier.padding(bottom = edge)
        Row(Modifier.fillMaxWidth().then(pad).padding(horizontal = inset), horizontalArrangement = Arrangement.SpaceBetween) {
            Tag(left)
            Tag(right)
        }
    }

    Column(Modifier.fillMaxSize()) {
        Band(ids[0], ids[1], top = true)
        Box(Modifier.weight(1f).fillMaxWidth()) { content() }
        Band(ids[3], ids[2], top = false)
    }
}
