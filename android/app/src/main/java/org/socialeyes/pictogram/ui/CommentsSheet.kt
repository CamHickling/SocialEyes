package org.socialeyes.pictogram.ui

import androidx.activity.compose.BackHandler
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animate
import androidx.compose.animation.core.spring
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshots.SnapshotStateMap
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.util.VelocityTracker
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.Velocity
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import org.socialeyes.pictogram.study.FeedPost
import org.socialeyes.pictogram.study.StudyPackage
import kotlin.math.abs
import kotlin.math.roundToInt

/** Where the comments sheet rests. */
enum class SheetState { HALF, FULL }

private const val FLING_VELOCITY = 1200f // px/s: a faster flick moves on to the next position

/**
 * The comments sheet, drawn in the feed's window (not a dialog, so the system
 * bars stay hidden). It opens part-way up; dragging the handle up, or scrolling
 * the list up, pulls it over the whole screen; dragging down returns it to
 * half height or closes it. Comments can be liked.
 *
 * [track] reports `sheet` and `sheet_comment_<n>` positions for viewport.csv,
 * [trackClip] the area comments are visible in; [onState] is called when the
 * sheet settles; [onClose] when it has closed.
 */
@Composable
fun CommentsSheet(
    pkg: StudyPackage,
    post: FeedPost,
    topInset: Dp,
    allowCommentLikes: Boolean,
    commentLikes: SnapshotStateMap<String, Boolean>,
    track: (element: String, LayoutCoordinates) -> Unit,
    trackClip: (LayoutCoordinates) -> Unit,
    onCommentLike: (index: Int, liked: Boolean) -> Unit,
    onState: (SheetState) -> Unit,
    onClose: () -> Unit,
) {
    val dark = isDarkTheme()
    val scope = rememberCoroutineScope()
    BoxWithConstraints(Modifier.fillMaxSize()) {
        val density = LocalDensity.current
        val fullY = with(density) { topInset.toPx() }
        val closedY = constraints.maxHeight.toFloat()
        val halfY = closedY * 0.40f
        var y by remember { mutableFloatStateOf(closedY) }
        var settled by remember { mutableStateOf<SheetState?>(null) }
        var closing by remember { mutableStateOf(false) }

        fun settleTo(target: Float, velocity: Float = 0f) {
            scope.launch {
                animate(y, target, velocity, spring(dampingRatio = Spring.DampingRatioNoBouncy, stiffness = 500f)) { v, _ -> y = v }
                when (target) {
                    closedY -> onClose()
                    fullY -> if (settled != SheetState.FULL) { settled = SheetState.FULL; onState(SheetState.FULL) }
                    else -> if (settled != SheetState.HALF) { settled = SheetState.HALF; onState(SheetState.HALF) }
                }
            }
        }

        /** Picks the resting position after a drag, from where it is and how fast it moved. */
        fun settle(velocity: Float) {
            val target = when {
                velocity > FLING_VELOCITY -> if (y < halfY - 1) halfY else closedY
                velocity < -FLING_VELOCITY -> fullY
                else -> listOf(fullY, halfY, closedY).minBy { abs(it - y) }
            }
            if (target == closedY) closing = true
            settleTo(target, velocity)
        }

        fun close() {
            if (closing) return
            closing = true
            settleTo(closedY)
        }

        LaunchedEffect(Unit) { settleTo(halfY) }
        BackHandler { close() }

        // Scrolling the list first moves the sheet: up until it is full screen,
        // and down (once the list is at its top) back towards half height or closed.
        val scroll = rememberScrollState()
        val nested = remember(fullY, closedY) {
            object : NestedScrollConnection {
                override fun onPreScroll(available: Offset, source: NestedScrollSource): Offset {
                    if (available.y < 0 && y > fullY) {
                        val used = maxOf(available.y, fullY - y)
                        y += used
                        return Offset(0f, used)
                    }
                    return Offset.Zero
                }

                override fun onPostScroll(consumed: Offset, available: Offset, source: NestedScrollSource): Offset {
                    if (available.y > 0 && source == NestedScrollSource.UserInput) {
                        val used = minOf(available.y, closedY - y)
                        y += used
                        return Offset(0f, used)
                    }
                    return Offset.Zero
                }

                override suspend fun onPreFling(available: Velocity): Velocity {
                    if (y != fullY && y != halfY) {
                        settle(available.y)
                        return available
                    }
                    return Velocity.Zero
                }
            }
        }

        // scrim
        val scrimAlpha = (0.4f * (1f - (y - fullY) / (closedY - fullY))).coerceIn(0f, 0.4f)
        Box(
            Modifier
                .fillMaxSize()
                .background(Color.Black.copy(alpha = scrimAlpha))
                .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) { close() },
        )

        Column(
            Modifier
                .offset { IntOffset(0, y.roundToInt()) }
                .fillMaxWidth()
                .height(with(density) { (closedY - fullY).toDp() })
                .background(MaterialTheme.colorScheme.background, RoundedCornerShape(topStart = 16.dp, topEnd = 16.dp))
                .onGloballyPositioned { track("sheet", it) }
                .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) {},
        ) {
            // handle and title: drag here to move the sheet
            Column(
                Modifier
                    .fillMaxWidth()
                    .pointerInput(Unit) {
                        val tracker = VelocityTracker()
                        detectVerticalDragGestures(
                            onDragStart = { tracker.resetTracking() },
                            onDragEnd = { settle(tracker.calculateVelocity().y) },
                            onDragCancel = { settle(0f) },
                        ) { change, dy ->
                            tracker.addPosition(change.uptimeMillis, change.position)
                            y = (y + dy).coerceIn(fullY, closedY)
                        }
                    },
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Spacer(Modifier.height(10.dp))
                Box(Modifier.size(width = 36.dp, height = 4.dp).background(FeedColors.secondary(dark), RoundedCornerShape(2.dp)))
                Text(
                    "Comments", fontWeight = FontWeight.SemiBold, fontSize = 16.sp, textAlign = TextAlign.Center,
                    color = MaterialTheme.colorScheme.onBackground,
                    modifier = Modifier.fillMaxWidth().padding(top = 14.dp, bottom = 12.dp),
                )
                HorizontalDivider(thickness = 0.5.dp, color = FeedColors.divider(dark))
            }

            Box(
                Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .clipToBounds()
                    .onGloballyPositioned(trackClip),
            ) {
                Column(Modifier.fillMaxSize().nestedScroll(nested).verticalScroll(scroll)) {
                    if (post.comments.isEmpty()) {
                        Column(Modifier.fillMaxWidth().padding(vertical = 48.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                            Text("No comments yet", fontSize = 22.sp, fontWeight = FontWeight.SemiBold,
                                color = MaterialTheme.colorScheme.onBackground)
                            Spacer(Modifier.height(6.dp))
                            Text("Start the conversation.", fontSize = 14.sp, color = FeedColors.secondary(dark))
                        }
                    }
                    post.comments.forEachIndexed { i, c ->
                        val key = "${post.postId}:$i"
                        val liked = commentLikes[key] == true
                        CommentRow(
                            pkg = pkg,
                            handle = pkg.handle(c),
                            avatar = pkg.manifest.accounts[c.accountId]?.avatar,
                            text = c.text,
                            likes = c.likeCount + if (liked) 1 else 0,
                            liked = liked,
                            dark = dark,
                            onLike = if (allowCommentLikes) {
                                {
                                    commentLikes[key] = !liked
                                    onCommentLike(i, !liked)
                                }
                            } else null,
                            modifier = Modifier.onGloballyPositioned { track("sheet_comment_$i", it) },
                        )
                    }
                    Spacer(Modifier.height(32.dp))
                }
            }
        }
    }
}

@Composable
private fun CommentRow(
    pkg: StudyPackage,
    handle: String,
    avatar: String?,
    text: String,
    likes: Int,
    liked: Boolean,
    dark: Boolean,
    onLike: (() -> Unit)?,
    modifier: Modifier,
) {
    val secondary = FeedColors.secondary(dark)
    Row(modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp, top = 10.dp, bottom = 10.dp)) {
        if (avatar != null) Avatar(pkg.file(avatar), 34.dp) else Spacer(Modifier.size(34.dp))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(handle, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onBackground)
            Text(text, fontSize = 14.sp, color = MaterialTheme.colorScheme.onBackground)
            Text("Reply", fontSize = 12.sp, color = secondary, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 4.dp))
        }
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier
                .width(44.dp)
                .then(
                    if (onLike != null) {
                        Modifier.clickable(interactionSource = remember { MutableInteractionSource() }, indication = null, onClick = onLike)
                    } else Modifier
                )
                .padding(top = 4.dp, bottom = 4.dp),
        ) {
            Icon(
                if (liked) FeedIcons.HeartFilled else FeedIcons.Heart, "like comment",
                tint = if (liked) FeedColors.LikeRed else secondary,
                modifier = Modifier.size(15.dp),
            )
            if (likes > 0) Text("$likes", fontSize = 11.sp, color = secondary)
        }
    }
}
