package org.socialeyes.pictogram.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.requiredSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.wrapContentHeight
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.graphics.ColorMatrix
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonPrimitive
import org.socialeyes.pictogram.Session
import org.socialeyes.pictogram.log.ScreenRect
import org.socialeyes.pictogram.study.Step
import org.socialeyes.pictogram.study.StudyPackage
import kotlin.math.roundToInt

/** Cells across each AprilTag family's black square (border included). */
internal val FAMILY_CELLS = mapOf("tag36h11" to 8, "tag25h9" to 7, "tag16h5" to 6)

private val CORNERS = listOf("top_left", "top_right", "bottom_right", "bottom_left")

/** One tag_bars variant: four tags (TL, TR, BR, BL) of a family, size and grey level. */
internal data class BarVariant(val family: String, val sizeMm: Double, val grey: Double, val ids: List<Int>) {
    val cells: Int get() = FAMILY_CELLS.getValue(family)
    val label: String
        get() = "${family.removePrefix("tag")} ${if (sizeMm % 1.0 == 0.0) sizeMm.toInt().toString() else sizeMm.toString()} mm" +
            if (grey > 0) " grey ${(grey * 100).roundToInt()}%" else ""
}

internal fun barVariants(step: Step): List<BarVariant> =
    (step.raw["variants"] as? JsonArray).orEmpty().mapNotNull { e ->
        val o = e as? JsonObject ?: return@mapNotNull null
        val ids = (o["tag_ids"] as? JsonArray)?.mapNotNull { it.jsonPrimitive.intOrNull } ?: return@mapNotNull null
        val family = o["family"]?.jsonPrimitive?.content ?: "tag16h5"
        val size = o["size_mm"]?.jsonPrimitive?.doubleOrNull ?: return@mapNotNull null
        if (ids.size != 4 || family !in FAMILY_CELLS) null
        else BarVariant(family, size, o["grey"]?.jsonPrimitive?.doubleOrNull ?: 0.0, ids)
    }

/** The variants' order in one hold: `rounds` rounds, alternately forwards and backwards (and the
 *  other way round in odd holds), so no variant always follows the same one. */
internal fun barOrder(n: Int, rounds: Int, hold: Int): List<Int> =
    (0 until rounds).flatMap { r -> if ((r + hold) % 2 == 0) (0 until n).toList() else (n - 1 downTo 0).toList() }

private val BAR_HOLDS = listOf(
    "Hold the phone the way you normally would.",
    "Hold the phone at arm's length: stretch your arm out fully.",
    "Rest the phone low, near your lap, and look down at it.",
)

/**
 * `tag_bars`: for each hold, a still copy of the feed with four tags of one variant in the
 * corners of the top bar and tab bar, `variant_s` seconds per variant. Each bar grows only as
 * much as its tags need. Logs a `marker_layout` (with `ladder`, as tag_ladder's, plus `bars`:
 * the variant and the bars' heights) for every variant shown.
 */
@Composable
fun TagBarsStep(session: Session, step: Step, onContinue: () -> Unit) =
    HoldSequence(session, step, BAR_HOLDS, onContinue) { hold, onDone -> BarsScreen(session, step, hold, onDone) }

@Composable
private fun BarsScreen(session: Session, step: Step, hold: Int, onDone: () -> Unit) {
    val variants = remember { barVariants(step) }
    val variantS = step.double("variant_s") ?: 4.0
    val order = remember(hold) { barOrder(variants.size, step.int("rounds") ?: 2, hold) }
    var phase by remember { mutableIntStateOf(0) }
    LaunchedEffect(Unit) {
        for (p in order.indices) {
            phase = p
            delay((variantS * 1000).toLong())
        }
        onDone()
    }
    if (variants.isEmpty()) return
    key(phase) { BarsLayout(session, step, hold, phase, variants[order[phase]]) }
}

@Composable
private fun BarsLayout(session: Session, step: Step, hold: Int, phase: Int, v: BarVariant) {
    val pkg = session.pkg
    val metrics = LocalContext.current.resources.displayMetrics
    val density = LocalDensity.current
    val view = LocalView.current
    val dark = isDarkTheme()
    val primary = MaterialTheme.colorScheme.onBackground
    fun Float.asDp(): Dp = with(density) { this@asDp.toDp() }

    val tags = rememberBarTags(v.family, v.ids, v.sizeMm, step.double("side_inset_mm") ?: 5.0, step.double("edge_gap_mm") ?: 2.0)
    // each bar grows only if its tags need it
    val sync = pkg.study.display.syncPatch
    val topStrip = if (sync.enabled) maxOf(24, sync.sizeDp + 16).dp else 0.dp
    val topBarH = maxOf(topStrip + 52.dp, tags.barPx.asDp())
    val tabBarH = maxOf(50.dp, tags.barPx.asDp())
    val clear = tags.clearPx.asDp()

    var origin by remember { mutableStateOf<Offset?>(null) }
    var boxPx by remember { mutableStateOf(Offset.Zero) }
    var feedPx by remember { mutableFloatStateOf(0f) }

    LaunchedEffect(origin, feedPx) {
        val o = origin ?: return@LaunchedEffect
        if (boxPx == Offset.Zero || feedPx == 0f) return@LaunchedEffect
        session.log.event(
            "marker_layout",
            fields = arrayOf(
                "step_id" to step.id,
                "tags" to v.ids.withIndex().associate { (k, id) -> id.toString() to tags.rect(k, boxPx).offset(o.x, o.y).toJson() },
                "ladder" to mapOf(
                    "hold" to hold, "phase" to phase,
                    "screen" to ScreenRect(o.x, o.y, o.x + boxPx.x, o.y + boxPx.y).toJson(),
                    "tags" to v.ids.withIndex().associate { (k, id) ->
                        id.toString() to mapOf(
                            "kind" to "bars", "value_mm" to v.sizeMm, "size_mm" to v.sizeMm, "family" to v.family,
                            "cells" to v.cells, "grey" to v.grey, "variant" to v.label, "corner" to CORNERS[k],
                        )
                    },
                    "bars" to mapOf(
                        "variant" to v.label, "top_bar_dp" to topBarH.value, "tab_bar_dp" to tabBarH.value,
                        "feed_px" to feedPx,
                    ),
                ),
            ),
        )
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
            // top bar: wordmark and icons between the top tags, at the bottom of the (taller) bar
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
            // the start of the feed, still
            Box(
                Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .clipToBounds()
                    .onGloballyPositioned { feedPx = it.size.height.toFloat() },
            ) {
                Column(Modifier.wrapContentHeight(Alignment.Top, unbounded = true)) {
                    val feed = session.plan.feed
                    StoriesTray(pkg, feed, emptyList(), emptyMap()) {}
                    feed.take(2).forEach { post ->
                        PostCard(
                            post = post, pkg = pkg, imageMaxWidth = metrics.widthPixels,
                            allowLikes = false, allowSaves = false, allowShares = false, onShared = {},
                            participantHandle = pkg.study.platform.participantHandle, ownComments = emptyList(),
                            track = { _, _ -> }, event = { _, _ -> }, onOpenComments = {},
                        )
                    }
                }
            }
            HorizontalDivider(thickness = 0.5.dp, color = FeedColors.divider(dark))
            // tab bar: the five tabs between the bottom tags
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

        // the tags, over the bars' corners
        val filter = if (v.grey > 0) {
            val s = 1f - v.grey.toFloat()
            val o = v.grey.toFloat() * 255f
            ColorFilter.colorMatrix(ColorMatrix(floatArrayOf(s, 0f, 0f, 0f, o, 0f, s, 0f, 0f, o, 0f, 0f, s, 0f, o, 0f, 0f, 0f, 1f, 0f)))
        } else null
        BarTagImages(pkg, tags, boxPx, filter)
    }
}

/**
 * Four tags (TL, TR, BR, BL) in the corners of a top bar and a tab bar, in pixels: tag_bars, and
 * the feed with `markers.on_screen` layout `bars`. The tags' black borders are `insetPx` from the
 * side edges and `edgePx` from the top and bottom edges; the bars keep a 1-cell quiet zone.
 */
internal class BarTags(val family: String, val ids: List<Int>, val tagPx: Float, val insetPx: Float, val edgePx: Float) {
    val cells: Int = FAMILY_CELLS.getValue(family)
    val cell: Float = tagPx / cells

    /** The least height a bar needs for its tags. */
    val barPx: Float get() = edgePx + tagPx + cell

    /** Bar content starts this far from the side edges. */
    val clearPx: Float get() = insetPx + tagPx + cell

    /** Tag k's whole image (the black square in a 2-cell white margin) in a box of `box` px. */
    fun rect(k: Int, box: Offset): ScreenRect {
        val img = cell * (cells + 4)
        val l = if (k == 0 || k == 3) insetPx - 2 * cell else box.x - insetPx - tagPx - 2 * cell
        val t = if (k < 2) edgePx - 2 * cell else box.y - edgePx - tagPx - 2 * cell
        return ScreenRect(l, t, l + img, t + img)
    }
}

@Composable
internal fun rememberBarTags(family: String, ids: List<Int>, sizeMm: Double, sideInsetMm: Double = 5.0, edgeGapMm: Double = 2.0): BarTags {
    val metrics = LocalContext.current.resources.displayMetrics
    return remember(family, ids, sizeMm, sideInsetMm, edgeGapMm) {
        BarTags(family, ids, (sizeMm / 25.4 * metrics.xdpi).toFloat(), (sideInsetMm / 25.4 * metrics.xdpi).toFloat(),
            (edgeGapMm / 25.4 * metrics.ydpi).toFloat())
    }
}

/** The tags of [tags] over a Box of `box` px, each showing a 1-cell quiet zone. */
@Composable
internal fun BarTagImages(pkg: StudyPackage, tags: BarTags, box: Offset, filter: ColorFilter? = null) {
    if (box == Offset.Zero) return
    val density = LocalDensity.current
    val cell = tags.cell
    tags.ids.forEachIndexed { k, id ->
        val bitmap by rememberImage(pkg.file("tags/${tags.family}_$id.png"), 0)
        val r = tags.rect(k, box)
        Box(
            Modifier
                .offset { IntOffset((r.left + cell).roundToInt(), (r.top + cell).roundToInt()) }
                .size(with(density) { (cell * (tags.cells + 2)).toDp() })
                .clipToBounds(),
            contentAlignment = Alignment.Center,
        ) {
            bitmap?.let {
                Image(it, "tag $id", Modifier.requiredSize(with(density) { (cell * (tags.cells + 4)).toDp() }),
                    contentScale = ContentScale.FillBounds, filterQuality = FilterQuality.None, colorFilter = filter)
            }
        }
    }
}
