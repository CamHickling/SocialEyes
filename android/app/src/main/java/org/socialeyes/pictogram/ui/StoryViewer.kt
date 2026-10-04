package org.socialeyes.pictogram.ui

import androidx.activity.compose.BackHandler
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.runtime.snapshotFlow
import kotlinx.coroutines.flow.collectLatest
import org.socialeyes.pictogram.log.Clocks
import org.socialeyes.pictogram.study.StoryItem
import org.socialeyes.pictogram.study.StudyPackage

/**
 * Full-screen story viewer, opened from a story circle. Each story runs for its
 * duration, then the next one (and the next account's stories) follows; tapping
 * the left third goes back, the rest forward; holding pauses; swiping down or
 * Back closes it.
 *
 * Logs (via [event]): `story_start` when a story appears and `story_end` when it
 * goes, with how it ended (`auto`, `tap_forward`, `tap_back`, `swipe_down`,
 * `close_button`, `back`), the time shown and the time paused. [track] reports
 * the story image's position for viewport.csv (element `story`).
 */
@Composable
fun StoryViewer(
    pkg: StudyPackage,
    groups: List<List<StoryItem>>,
    startGroup: Int,
    topInset: Dp,
    track: (storyId: String, LayoutCoordinates) -> Unit,
    event: (type: String, fields: Array<Pair<String, Any?>>) -> Unit,
    onSeen: (storyId: String) -> Unit,
    onClose: (reason: String) -> Unit,
) {
    var group by remember { mutableIntStateOf(startGroup) }
    var index by remember { mutableIntStateOf(0) }
    var paused by remember { mutableStateOf(false) }
    var closed by remember { mutableStateOf(false) }
    val progress = remember { Animatable(0f) }
    var shownSinceNs by remember { mutableLongStateOf(Clocks.elapsedNs()) }
    var pausedNs by remember { mutableLongStateOf(0L) }
    var pauseStartNs by remember { mutableLongStateOf(0L) }
    var dragY by remember { mutableFloatStateOf(0f) }
    var restart by remember { mutableIntStateOf(0) } // bumped to replay the first story

    val story = groups[group][index]
    val account = pkg.manifest.accounts[story.accountId]

    fun start() {
        shownSinceNs = Clocks.elapsedNs()
        pausedNs = 0L
        onSeen(story.storyId)
        event("story_start", arrayOf("story_id" to story.storyId, "account_id" to story.accountId))
    }

    fun end(reason: String) {
        val now = Clocks.elapsedNs()
        val extraPause = if (paused && pauseStartNs > 0) now - pauseStartNs else 0L
        event(
            "story_end", arrayOf(
                "story_id" to story.storyId, "account_id" to story.accountId, "reason" to reason,
                "shown_ms" to (now - shownSinceNs) / 1_000_000, "paused_ms" to (pausedNs + extraPause) / 1_000_000,
            )
        )
    }

    fun close(reason: String) {
        if (closed) return
        closed = true
        end(reason)
        onClose(reason)
    }

    fun show(g: Int, i: Int) {
        group = g
        index = i
        paused = false
    }

    fun next(reason: String) {
        if (closed) return
        when {
            index + 1 < groups[group].size -> { end(reason); show(group, index + 1) }
            group + 1 < groups.size -> { end(reason); show(group + 1, 0) }
            else -> close(reason) // the last story of the last account
        }
    }

    fun previous() {
        if (closed) return
        when {
            index > 0 -> { end("tap_back"); show(group, index - 1) }
            group > 0 -> { end("tap_back"); show(group - 1, 0) }
            else -> { end("tap_back"); restart++ } // first story: start it again
        }
    }

    // A new story: reset and log it, then run its progress bar, stopping while paused.
    // One coroutine per story, so the bar always starts from zero.
    LaunchedEffect(group, index, restart) {
        progress.snapTo(0f)
        start()
        val totalMs = (story.durationS * 1000).toInt()
        snapshotFlow { paused }.collectLatest { isPaused ->
            if (!isPaused) {
                progress.animateTo(1f, tween(((1f - progress.value) * totalMs).toInt().coerceAtLeast(1), easing = LinearEasing))
                next("auto")
            }
        }
    }

    BackHandler { close("back") }

    Box(
        Modifier
            .fillMaxSize()
            .background(Color.Black)
            .graphicsLayer {
                translationY = dragY.coerceAtLeast(0f)
                val s = 1f - (dragY.coerceAtLeast(0f) / 3000f)
                scaleX = s
                scaleY = s
            }
            // keyed by the story, so the handlers always log the story on screen
            .pointerInput(group, index, restart) {
                detectTapGestures(
                    onPress = {
                        paused = true
                        pauseStartNs = Clocks.elapsedNs()
                        tryAwaitRelease()
                        pausedNs += Clocks.elapsedNs() - pauseStartNs
                        pauseStartNs = 0L
                        paused = false
                    },
                    // a hold only pauses; letting go must not also count as a tap
                    onLongPress = {},
                    onTap = { offset -> if (offset.x < size.width * 0.3f) previous() else next("tap_forward") },
                )
            }
            .pointerInput(group, index, restart) {
                detectVerticalDragGestures(
                    onDragEnd = { if (dragY > 250f) close("swipe_down") else dragY = 0f },
                    onDragCancel = { dragY = 0f },
                ) { _, dy -> dragY += dy }
            },
    ) {
        val screenW = LocalConfiguration.current.screenWidthDp
        val maxPx = with(LocalDensity.current) { screenW.dp.roundToPx() }
        // the story image, whole and at its own aspect ratio, so gaze maps to image pixels
        Box(
            Modifier
                .padding(top = topInset)
                .fillMaxWidth()
                .aspectRatio(story.width.toFloat() / story.height)
                .clip(RoundedCornerShape(10.dp))
                .onGloballyPositioned { track(story.storyId, it) },
        ) {
            val bitmap by rememberImage(pkg.file(story.file), maxPx)
            bitmap?.let { Image(it, null, Modifier.fillMaxSize(), contentScale = ContentScale.FillBounds) }

            Column(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp)) {
                // progress bars, one per story of this account
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    groups[group].forEachIndexed { i, _ ->
                        val fill = when {
                            i < index -> 1f
                            i == index -> progress.value
                            else -> 0f
                        }
                        Box(
                            Modifier.weight(1f).height(2.5.dp).clip(RoundedCornerShape(2.dp))
                                .background(Color.White.copy(alpha = 0.35f)),
                        ) {
                            Box(Modifier.fillMaxHeight().fillMaxWidth(fill).background(Color.White))
                        }
                    }
                }
                Spacer(Modifier.height(10.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (account != null) Avatar(pkg.file(account.avatar), 32.dp)
                    Spacer(Modifier.width(10.dp))
                    Text(account?.handle ?: story.accountId, color = Color.White, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                    story.postedAgo?.takeIf { it.isNotBlank() }?.let {
                        Text("  $it", color = Color.White.copy(alpha = 0.7f), fontSize = 14.sp)
                    }
                    Spacer(Modifier.weight(1f))
                    Icon(FeedIcons.MoreVertical, null, tint = Color.White, modifier = Modifier.size(20.dp))
                    Text(
                        "✕", color = Color.White, fontSize = 22.sp,
                        modifier = Modifier.clickable { close("close_button") }.padding(start = 16.dp, end = 4.dp),
                    )
                }
            }
        }

        // reply bar, for the look only
        Row(
            Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(horizontal = 14.dp, vertical = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                Modifier.weight(1f).height(44.dp).border(1.dp, Color.White.copy(alpha = 0.7f), RoundedCornerShape(22.dp))
                    .padding(horizontal = 18.dp),
                contentAlignment = Alignment.CenterStart,
            ) { Text("Send message", color = Color.White, fontSize = 14.sp) }
            Spacer(Modifier.width(16.dp))
            Icon(FeedIcons.Heart, null, tint = Color.White, modifier = Modifier.size(26.dp))
            Spacer(Modifier.width(16.dp))
            Icon(FeedIcons.Share, null, tint = Color.White, modifier = Modifier.size(26.dp))
        }
    }
}
