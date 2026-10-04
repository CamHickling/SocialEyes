package org.socialeyes.pictogram.ui

import androidx.activity.compose.BackHandler
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.runtime.key
import androidx.compose.runtime.snapshots.SnapshotStateMap
import androidx.compose.ui.draw.scale
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
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
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.util.VelocityTracker
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import org.socialeyes.pictogram.log.Clocks
import org.socialeyes.pictogram.study.StoryItem
import org.socialeyes.pictogram.study.StudyPackage
import kotlin.math.abs
import kotlin.math.roundToInt

private const val SWIPE_COMPLETE = 0.35f // fraction of the screen width that completes a swipe
private const val SWIPE_FLING = 1500f // px/s: a quick flick completes it too

/**
 * Full-screen story viewer, opened from a story circle. Each story runs for its
 * duration, then the next one (and the next account's stories) follows. Tapping
 * the left third goes back, the rest forward; holding pauses; swiping sideways
 * turns, like a cube, to the next or previous account (dragging part way and
 * letting go is a "peek" that snaps back); swiping down or Back closes it.
 *
 * Logs (via [event]): `story_start` / `story_end` per story (reason `auto`,
 * `tap_forward`, `tap_back`, `swipe_next`, `swipe_back`, `swipe_down`,
 * `close_button`, `back`, with time shown and time paused) and `story_swipe`
 * for every sideways drag (direction, how far it got, whether it completed).
 * [track] / [untrack] report each visible story image for viewport.csv
 * (element `story`; while swiping, the current and the peeked story).
 *
 * The reply bar works: typing a message pauses the story (`story_reply_edit` for
 * every change of the draft, `story_reply` with the text when sent), the heart
 * likes the story (`story_like`) and the paper plane shows "Sent" (`story_share`).
 */
@Composable
fun StoryViewer(
    pkg: StudyPackage,
    groups: List<List<StoryItem>>,
    startGroup: Int,
    topInset: Dp,
    track: (storyId: String, LayoutCoordinates) -> Unit,
    untrack: (storyId: String) -> Unit,
    event: (type: String, fields: Array<Pair<String, Any?>>) -> Unit,
    onSeen: (storyId: String) -> Unit,
    onClose: (reason: String) -> Unit,
    allowReplies: Boolean,
    allowLikes: Boolean,
    allowShares: Boolean,
    storyLikes: SnapshotStateMap<String, Boolean>,
) {
    val scope = rememberCoroutineScope()
    val focus = LocalFocusManager.current
    // reply box
    var draft by remember { mutableStateOf(TextFieldValue("")) }
    var fieldKey by remember { mutableIntStateOf(0) } // new text field after sending (see CommentsSheet)
    var replyFocused by remember { mutableStateOf(false) }
    var draftStartNs by remember { mutableStateOf<Long?>(null) }
    var toast by remember { mutableStateOf<Pair<String, Long>?>(null) }
    var group by remember { mutableIntStateOf(startGroup) }
    var index by remember { mutableIntStateOf(0) }
    var paused by remember { mutableStateOf(false) }
    var closed by remember { mutableStateOf(false) }
    var restart by remember { mutableIntStateOf(0) } // bumped to replay the first story
    val progress = remember { Animatable(0f) }
    var shownSinceNs by remember { mutableLongStateOf(Clocks.elapsedNs()) }
    var pausedNs by remember { mutableLongStateOf(0L) }
    var pauseStartNs by remember { mutableLongStateOf(0L) }
    var dragY by remember { mutableFloatStateOf(0f) }
    val swipe = remember { Animatable(0f) } // -1 = fully turned to the next account, +1 = to the previous
    var swipeMax by remember { mutableFloatStateOf(0f) }

    val story = groups[group][index]

    fun pause() {
        if (paused) return
        paused = true
        pauseStartNs = Clocks.elapsedNs()
    }

    fun resume() {
        if (!paused) return
        pausedNs += Clocks.elapsedNs() - pauseStartNs
        pauseStartNs = 0L
        paused = false
    }

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
        pauseStartNs = 0L
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

    BoxWithConstraints(
        Modifier
            .fillMaxSize()
            .background(Color.Black)
            .graphicsLayer {
                translationY = dragY.coerceAtLeast(0f)
                val s = 1f - (dragY.coerceAtLeast(0f) / 3000f)
                scaleX = s
                scaleY = s
            },
    ) {
        val widthPx = constraints.maxWidth.toFloat()
        val hasNext = group + 1 < groups.size
        val hasPrevious = group > 0

        // sideways: turn to the next / previous account
        fun endSwipe(velocity: Float) {
            val f = swipe.value
            val direction = if (f < 0) "next" else "previous"
            val complete = (f < 0 && (f <= -SWIPE_COMPLETE || velocity < -SWIPE_FLING)) ||
                (f > 0 && hasPrevious && (f >= SWIPE_COMPLETE || velocity > SWIPE_FLING))
            if (abs(swipeMax) > 0.02f) {
                event(
                    "story_swipe", arrayOf(
                        "story_id" to story.storyId, "direction" to direction,
                        "max_fraction" to (abs(swipeMax) * 100).roundToInt() / 100.0, "completed" to complete,
                    )
                )
            }
            swipeMax = 0f
            scope.launch {
                if (complete) {
                    swipe.animateTo(if (f < 0) -1f else 1f, tween(180))
                    when {
                        f < 0 && hasNext -> { end("swipe_next"); show(group + 1, 0) }
                        f < 0 -> close("swipe_next") // past the last account
                        else -> { end("swipe_back"); show(group - 1, 0) }
                    }
                    swipe.snapTo(0f)
                } else {
                    swipe.animateTo(0f, tween(180))
                    resume()
                }
            }
        }

        val gestures = Modifier
            // keyed by the story, so the handlers always log the story on screen
            .pointerInput(group, index, restart) {
                detectTapGestures(
                    onPress = {
                        if (replyFocused) return@detectTapGestures
                        pause()
                        tryAwaitRelease()
                        if (swipe.value == 0f) resume()
                    },
                    // a hold only pauses; letting go must not also count as a tap
                    onLongPress = {},
                    onTap = { offset ->
                        when {
                            replyFocused -> focus.clearFocus() // close the keyboard, stay on the story
                            offset.x < size.width * 0.3f -> previous()
                            else -> next("tap_forward")
                        }
                    },
                )
            }
            .pointerInput(group, index, restart) {
                detectVerticalDragGestures(
                    onDragEnd = { if (dragY > 250f) close("swipe_down") else dragY = 0f },
                    onDragCancel = { dragY = 0f },
                ) { _, dy -> dragY += dy }
            }
            .pointerInput(group, index, restart) {
                val tracker = VelocityTracker()
                detectHorizontalDragGestures(
                    onDragStart = { tracker.resetTracking(); pause() },
                    onDragEnd = { endSwipe(tracker.calculateVelocity().x) },
                    onDragCancel = { endSwipe(0f) },
                ) { change, dx ->
                    tracker.addPosition(change.uptimeMillis, change.position)
                    // no previous account: only a little give; past the last one, the viewer closes
                    val upper = if (hasPrevious) 1f else 0.15f
                    val f = (swipe.value + dx / widthPx).coerceIn(-1f, upper)
                    if (abs(f) > abs(swipeMax)) swipeMax = f
                    scope.launch { swipe.snapTo(f) }
                }
            }

        val f = swipe.value
        val distance = 12f * LocalDensity.current.density
        Box(Modifier.fillMaxSize().then(gestures)) {
            // the account we're turning to, entering from the side it's on
            val neighbour = when {
                f < 0 && hasNext -> group + 1
                f > 0 && hasPrevious -> group - 1
                else -> null
            }
            if (neighbour != null) {
                StoryPage(
                    pkg, groups[neighbour], 0, 0f, topInset, track, untrack, ::close, { StaticReplyBar() },
                    Modifier.graphicsLayer {
                        cameraDistance = distance
                        if (f < 0) {
                            transformOrigin = TransformOrigin(0f, 0.5f)
                            translationX = widthPx * (1f + f)
                            rotationY = 90f * (1f + f)
                        } else {
                            transformOrigin = TransformOrigin(1f, 0.5f)
                            translationX = -widthPx * (1f - f)
                            rotationY = -90f * (1f - f)
                        }
                    },
                )
            }
            StoryPage(
                pkg, groups[group], index, progress.value, topInset, track, untrack, ::close,
                {
                    ReplyBar(
                        draft = draft,
                        fieldKey = fieldKey,
                        handle = pkg.manifest.accounts[story.accountId]?.handle.orEmpty(),
                        liked = storyLikes[story.storyId] == true,
                        allowReplies = allowReplies,
                        allowLikes = allowLikes,
                        allowShares = allowShares,
                        onDraft = { value ->
                            if (value.text != draft.text) {
                                if (draftStartNs == null && value.text.isNotEmpty()) draftStartNs = Clocks.elapsedNs()
                                event("story_reply_edit", arrayOf("story_id" to story.storyId, "text" to value.text))
                            }
                            draft = value
                        },
                        onFocus = { focused ->
                            replyFocused = focused
                            if (focused) pause() else resume()
                        },
                        onSend = {
                            val text = draft.text.trim()
                            val typingMs = draftStartNs?.let { (Clocks.elapsedNs() - it) / 1_000_000 }
                            event("story_reply", arrayOf("story_id" to story.storyId, "text" to text, "typing_ms" to typingMs))
                            draftStartNs = null
                            focus.clearFocus()
                            fieldKey++
                            draft = TextFieldValue("")
                            toast = "Sent" to System.nanoTime()
                        },
                        onLike = {
                            val now = storyLikes[story.storyId] != true
                            storyLikes[story.storyId] = now
                            event("story_like", arrayOf("story_id" to story.storyId, "liked" to now))
                        },
                        onShare = {
                            event("story_share", arrayOf("story_id" to story.storyId))
                            toast = "Sent" to System.nanoTime()
                        },
                    )
                },
                Modifier.graphicsLayer {
                    cameraDistance = distance
                    transformOrigin = if (f < 0) TransformOrigin(1f, 0.5f) else TransformOrigin(0f, 0.5f)
                    translationX = widthPx * f
                    rotationY = 90f * f
                },
            )
        }

        toast?.let { (text, id) ->
            LaunchedEffect(id) {
                kotlinx.coroutines.delay(1500)
                toast = null
            }
            Box(
                Modifier.align(Alignment.BottomCenter).padding(bottom = 96.dp)
                    .background(Color(0xE6262626), RoundedCornerShape(8.dp))
                    .padding(horizontal = 18.dp, vertical = 10.dp),
            ) { Text(text, color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.SemiBold) }
        }
    }
}

/** One story: the image (whole, at its own aspect ratio), progress bars, header and reply bar. */
@Composable
private fun StoryPage(
    pkg: StudyPackage,
    stories: List<StoryItem>,
    index: Int,
    progress: Float,
    topInset: Dp,
    track: (storyId: String, LayoutCoordinates) -> Unit,
    untrack: (storyId: String) -> Unit,
    close: (reason: String) -> Unit,
    bottomBar: @Composable () -> Unit,
    modifier: Modifier,
) {
    val story = stories[index]
    val account = pkg.manifest.accounts[story.accountId]
    DisposableEffect(story.storyId) { onDispose { untrack(story.storyId) } }
    // The image above the reply bar, never under it: if the screen is too short for
    // both, the image gets a little narrower (it is never cropped).
    Column(modifier.fillMaxSize().background(Color.Black)) {
        val maxPx = with(LocalDensity.current) { LocalConfiguration.current.screenWidthDp.dp.roundToPx() }
        Box(Modifier.weight(1f).fillMaxWidth().padding(top = topInset), contentAlignment = Alignment.TopCenter) {
        Box(
            Modifier
                .aspectRatio(story.width.toFloat() / story.height)
                .clip(RoundedCornerShape(10.dp))
                .onGloballyPositioned { track(story.storyId, it) },
        ) {
            val bitmap by rememberImage(pkg.file(story.file), maxPx)
            bitmap?.let { Image(it, null, Modifier.fillMaxSize(), contentScale = ContentScale.FillBounds) }

            Column(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp)) {
                // progress bars, one per story of this account
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    stories.forEachIndexed { i, _ ->
                        val fill = when {
                            i < index -> 1f
                            i == index -> progress
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
                // The handle gives way (with "…") when the story is narrow, e.g. while the
                // keyboard is open, so the ⋮ and ✕ always keep their place at the right.
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (account != null) Avatar(pkg.file(account.avatar), 32.dp)
                    Spacer(Modifier.width(10.dp))
                    Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            account?.handle ?: story.accountId, color = Color.White, fontWeight = FontWeight.SemiBold,
                            fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f, fill = false),
                        )
                        story.postedAgo?.takeIf { it.isNotBlank() }?.let {
                            Text("  $it", color = Color.White.copy(alpha = 0.7f), fontSize = 14.sp, maxLines = 1, softWrap = false)
                        }
                    }
                    Icon(FeedIcons.MoreVertical, null, tint = Color.White, modifier = Modifier.padding(start = 8.dp).size(20.dp))
                    Text(
                        "✕", color = Color.White, fontSize = 22.sp,
                        modifier = Modifier.clickable { close("close_button") }.padding(start = 14.dp, end = 4.dp),
                    )
                }
            }
        }
        }

        bottomBar()
    }
}

/** The reply bar of the story on screen: message box (with Send while typing), like, share. */
@Composable
private fun ReplyBar(
    draft: TextFieldValue,
    fieldKey: Int,
    handle: String,
    liked: Boolean,
    allowReplies: Boolean,
    allowLikes: Boolean,
    allowShares: Boolean,
    onDraft: (TextFieldValue) -> Unit,
    onFocus: (Boolean) -> Unit,
    onSend: () -> Unit,
    onLike: () -> Unit,
    onShare: () -> Unit,
) {
    val bounce = remember { Animatable(1f) }
    val scope = rememberCoroutineScope()
    val quiet = remember { MutableInteractionSource() }
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.weight(1f).heightIn(min = 44.dp).border(1.dp, Color.White.copy(alpha = 0.7f), RoundedCornerShape(22.dp))
                .padding(horizontal = 18.dp, vertical = 10.dp),
            contentAlignment = Alignment.CenterStart,
        ) {
            if (allowReplies) {
                key(fieldKey) {
                    BasicTextField(
                        value = draft,
                        onValueChange = onDraft,
                        textStyle = TextStyle(color = Color.White, fontSize = 14.sp),
                        cursorBrush = SolidColor(Color.White),
                        keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
                        maxLines = 3,
                        modifier = Modifier.fillMaxWidth().onFocusChanged { onFocus(it.isFocused) },
                        decorationBox = { inner ->
                            Box {
                                if (draft.text.isEmpty()) Text("Reply to $handle…", color = Color.White, fontSize = 14.sp)
                                inner()
                            }
                        },
                    )
                }
            } else {
                Text("Send message", color = Color.White, fontSize = 14.sp)
            }
        }
        if (draft.text.isNotBlank()) {
            Text(
                "Send", color = Color.White, fontWeight = FontWeight.SemiBold, fontSize = 15.sp,
                modifier = Modifier.clickable(interactionSource = quiet, indication = null, onClick = onSend)
                    .padding(start = 16.dp, top = 8.dp, bottom = 8.dp, end = 4.dp),
            )
        } else {
            Spacer(Modifier.width(16.dp))
            Icon(
                if (liked) FeedIcons.HeartFilled else FeedIcons.Heart, "like story",
                tint = if (liked) FeedColors.LikeRed else Color.White,
                modifier = Modifier
                    .size(26.dp)
                    .scale(bounce.value)
                    .then(
                        if (allowLikes) Modifier.clickable(interactionSource = quiet, indication = null) {
                            onLike()
                            if (!liked) scope.launch {
                                bounce.snapTo(0.7f)
                                bounce.animateTo(1f, spring(dampingRatio = Spring.DampingRatioMediumBouncy, stiffness = Spring.StiffnessMedium))
                            }
                        } else Modifier
                    ),
            )
            Spacer(Modifier.width(16.dp))
            Icon(
                FeedIcons.Share, "send story", tint = Color.White,
                modifier = Modifier.size(26.dp)
                    .then(if (allowShares) Modifier.clickable(interactionSource = quiet, indication = null, onClick = onShare) else Modifier),
            )
        }
    }
}

/** The reply bar of a story that is only being peeked at while swiping. */
@Composable
private fun StaticReplyBar() {
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 10.dp),
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
