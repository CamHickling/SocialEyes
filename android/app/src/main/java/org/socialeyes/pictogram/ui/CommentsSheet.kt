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
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshots.SnapshotStateMap
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.util.VelocityTracker
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.Velocity
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import org.socialeyes.pictogram.study.FeedPost
import org.socialeyes.pictogram.study.StudyPackage
import java.io.File
import kotlin.math.abs
import kotlin.math.roundToInt

/** Where the comments sheet rests. */
enum class SheetState { HALF, FULL }

/**
 * A comment or reply the participant wrote. [id] is `p1`, `p2`, … for the session;
 * study comments are referred to by their position, `0`, `1`, …
 * [replyTo] is the comment answered (null for a new comment); [thread] the
 * top-level comment the reply is shown under.
 */
data class OwnComment(val id: String, val text: String, val replyTo: String?, val thread: String?)

/** The comment being replied to, shown above the comment box. */
private data class ReplyTarget(val id: String, val thread: String, val handle: String)

private const val FLING_VELOCITY = 1200f // px/s: a faster flick moves on to the next position

/**
 * The comments sheet, drawn in the feed's window (not a dialog, so the system
 * bars stay hidden). It opens part-way up; dragging the handle up, or scrolling
 * the list up, pulls it over the whole screen; dragging down returns it to
 * half height or closes it. Comments can be liked; with [allowTyping] the
 * participant can comment and reply (the sheet goes full screen while typing).
 *
 * [track] reports `sheet`, `sheet_input` and `sheet_comment_<id>` positions for
 * viewport.csv, [trackClip] the area comments are visible in; [onState] is called
 * when the sheet settles; [onClose] when it has closed.
 */
@Composable
fun CommentsSheet(
    pkg: StudyPackage,
    post: FeedPost,
    topInset: Dp,
    allowCommentLikes: Boolean,
    allowTyping: Boolean,
    participantHandle: String,
    ownComments: List<OwnComment>,
    commentLikes: SnapshotStateMap<String, Boolean>,
    track: (element: String, LayoutCoordinates) -> Unit,
    trackClip: (LayoutCoordinates) -> Unit,
    onCommentLike: (id: String, liked: Boolean) -> Unit,
    onDraftChange: (text: String, replyTo: String?) -> Unit,
    onSubmit: (text: String, replyTo: String?, thread: String?) -> Unit,
    onState: (SheetState) -> Unit,
    onClose: () -> Unit,
) {
    val dark = isDarkTheme()
    val scope = rememberCoroutineScope()
    val focus = LocalFocusManager.current
    val keyboard = LocalSoftwareKeyboardController.current
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
            if (target == closedY) {
                closing = true
                focus.clearFocus()
            }
            settleTo(target, velocity)
        }

        fun close() {
            if (closing) return
            closing = true
            focus.clearFocus()
            settleTo(closedY)
        }

        LaunchedEffect(Unit) { settleTo(halfY) }
        BackHandler { close() }

        // comment box state
        var draft by remember { mutableStateOf(TextFieldValue("")) }
        var replyTarget by remember { mutableStateOf<ReplyTarget?>(null) }
        val inputFocus = remember { FocusRequester() }
        // A new text field after each post: the keyboard may still send its unfinished
        // word to the old one, which must not bring the posted text back.
        var fieldKey by remember { mutableIntStateOf(0) }

        fun startReply(target: ReplyTarget) {
            replyTarget = target
            val text = "@${target.handle} "
            draft = TextFieldValue(text, TextRange(text.length))
            onDraftChange(text, target.id)
            inputFocus.requestFocus()
            keyboard?.show()
        }

        fun submit() {
            val text = draft.text.trim()
            if (text.isEmpty()) return
            onSubmit(text, replyTarget?.id, replyTarget?.thread)
            focus.clearFocus()
            keyboard?.hide()
            fieldKey++
            draft = TextFieldValue("")
            replyTarget = null
        }

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
                    if (post.comments.isEmpty() && ownComments.none { it.thread == null }) {
                        Column(Modifier.fillMaxWidth().padding(vertical = 48.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                            Text("No comments yet", fontSize = 22.sp, fontWeight = FontWeight.SemiBold,
                                color = MaterialTheme.colorScheme.onBackground)
                            Spacer(Modifier.height(6.dp))
                            Text("Start the conversation.", fontSize = 14.sp, color = FeedColors.secondary(dark))
                        }
                    }

                    @Composable
                    fun CommentLine(id: String, handle: String, avatar: File?, text: String, baseLikes: Int, thread: String, reply: Boolean) {
                        val key = "${post.postId}:$id"
                        val liked = commentLikes[key] == true
                        CommentRow(
                            pkg = pkg,
                            handle = handle,
                            avatar = avatar,
                            text = text,
                            likes = baseLikes + if (liked) 1 else 0,
                            liked = liked,
                            dark = dark,
                            reply = reply,
                            onLike = if (allowCommentLikes) {
                                {
                                    commentLikes[key] = !liked
                                    onCommentLike(id, !liked)
                                }
                            } else null,
                            onReply = if (allowTyping) {
                                { startReply(ReplyTarget(id, thread, handle)) }
                            } else null,
                            modifier = Modifier.onGloballyPositioned { track("sheet_comment_$id", it) },
                        )
                    }

                    @Composable
                    fun Replies(thread: String) {
                        ownComments.filter { it.thread == thread }.forEach {
                            CommentLine(it.id, participantHandle, null, it.text, 0, thread, reply = true)
                        }
                    }

                    // study comments, each followed by the participant's replies to it
                    post.comments.forEachIndexed { i, c ->
                        val id = c.commentId.ifEmpty { "$i" } // packages compiled before comment ids: position
                        CommentLine(id, pkg.handle(c), pkg.manifest.accounts[c.accountId]?.avatar?.let(pkg::file), c.text, c.likeCount, id, reply = false)
                        Replies(id)
                    }
                    // the participant's own comments, oldest first
                    ownComments.filter { it.thread == null }.forEach {
                        CommentLine(it.id, participantHandle, null, it.text, 0, it.id, reply = false)
                        Replies(it.id)
                    }
                    Spacer(Modifier.height(if (allowTyping) 110.dp else 32.dp)) // room above the comment box
                }
            }
        }

        // Comment box, pinned to the bottom of the screen while the sheet is open.
        if (allowTyping) {
            val secondary = FeedColors.secondary(dark)
            Column(
                Modifier
                    .align(Alignment.BottomCenter)
                    .offset { IntOffset(0, (y - halfY).coerceAtLeast(0f).roundToInt()) }
                    .fillMaxWidth()
                    .background(MaterialTheme.colorScheme.background)
                    .onGloballyPositioned { track("sheet_input", it) }
                    .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) {},
            ) {
                replyTarget?.let { target ->
                    Row(
                        Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceVariant)
                            .padding(horizontal = 16.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text("Replying to ${target.handle}", fontSize = 13.sp, color = secondary, modifier = Modifier.weight(1f))
                        Text(
                            "✕", fontSize = 15.sp, color = secondary,
                            modifier = Modifier.clickable {
                                replyTarget = null
                                draft = TextFieldValue("")
                                onDraftChange("", null)
                            }.padding(horizontal = 4.dp),
                        )
                    }
                }
                HorizontalDivider(thickness = 0.5.dp, color = FeedColors.divider(dark))
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    ParticipantAvatar(34.dp, dark)
                    Spacer(Modifier.width(12.dp))
                    val poster = pkg.manifest.accounts[post.accountId]?.handle.orEmpty()
                    key(fieldKey) { BasicTextField(
                        value = draft,
                        onValueChange = {
                            if (it.text != draft.text) onDraftChange(it.text, replyTarget?.id)
                            draft = it
                        },
                        textStyle = TextStyle(fontSize = 14.sp, color = MaterialTheme.colorScheme.onBackground),
                        cursorBrush = SolidColor(MaterialTheme.colorScheme.onBackground),
                        keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
                        maxLines = 4,
                        modifier = Modifier
                            .weight(1f)
                            .focusRequester(inputFocus)
                            .onFocusChanged { if (it.isFocused && y > fullY) settleTo(fullY) },
                        decorationBox = { inner ->
                            Box {
                                if (draft.text.isEmpty()) {
                                    Text(
                                        if (replyTarget != null) "Add a reply…" else "Add a comment for $poster…",
                                        fontSize = 14.sp, color = secondary,
                                    )
                                }
                                inner()
                            }
                        },
                    ) }
                    val canPost = draft.text.isNotBlank()
                    Text(
                        "Post",
                        fontSize = 14.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = if (canPost) FeedColors.Blue else FeedColors.Blue.copy(alpha = 0.4f),
                        modifier = Modifier
                            .clickable(enabled = canPost, interactionSource = remember { MutableInteractionSource() }, indication = null) { submit() }
                            .padding(start = 12.dp, top = 6.dp, bottom = 6.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun CommentRow(
    pkg: StudyPackage,
    handle: String,
    avatar: File?,
    text: String,
    likes: Int,
    liked: Boolean,
    dark: Boolean,
    reply: Boolean,
    onLike: (() -> Unit)?,
    onReply: (() -> Unit)?,
    modifier: Modifier,
) {
    val secondary = FeedColors.secondary(dark)
    val avatarSize = if (reply) 26.dp else 34.dp
    Row(modifier.fillMaxWidth().padding(start = if (reply) 62.dp else 16.dp, end = 8.dp, top = 10.dp, bottom = 10.dp)) {
        if (avatar != null) Avatar(avatar, avatarSize) else ParticipantAvatar(avatarSize, dark) // null: the participant's own
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(handle, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onBackground)
            Text(text, fontSize = 14.sp, color = MaterialTheme.colorScheme.onBackground)
            Text(
                "Reply", fontSize = 12.sp, color = secondary, fontWeight = FontWeight.SemiBold,
                modifier = Modifier
                    .then(if (onReply != null) Modifier.clickable(onClick = onReply) else Modifier)
                    .padding(top = 4.dp, bottom = 2.dp, end = 12.dp),
            )
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
