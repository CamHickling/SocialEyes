package org.socialeyes.pictogram.ui

import android.view.ViewTreeObserver
import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.IntOffset
import kotlin.math.roundToInt
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import org.socialeyes.pictogram.R
import org.socialeyes.pictogram.Session
import org.socialeyes.pictogram.log.Clocks
import org.socialeyes.pictogram.log.ScreenRect
import org.socialeyes.pictogram.log.ViewportTracker
import org.socialeyes.pictogram.study.FeedPost
import org.socialeyes.pictogram.study.Step
import org.socialeyes.pictogram.study.StudyPackage

private val Wordmark = FontFamily(Font(R.font.grand_hotel))

/**
 * The feed step: the participant's posts in plan order. Logs viewport.csv,
 * feed interactions, the done button and the time limit.
 */
@Composable
fun FeedScreen(session: Session, step: Step, onDone: (reason: String) -> Unit) {
    val instructions = step.str("instructions").orEmpty()
    var started by remember { mutableStateOf(instructions.isBlank()) }
    if (started) {
        FeedContent(session, onDone)
    } else {
        MessageScreen(title = "", text = instructions, button = "Start") {
            session.log.event("feed_start")
            started = true
        }
    }
}

@Composable
private fun FeedContent(session: Session, onDone: (reason: String) -> Unit) {
    val pkg = session.pkg
    val log = session.log
    val cfg = pkg.study.feed
    val view = LocalView.current
    val listState = rememberLazyListState()
    val tracker = remember { ViewportTracker(log) }
    val imageMaxWidth = with(LocalDensity.current) { LocalConfiguration.current.screenWidthDp.dp.roundToPx() }
    var finished by remember { mutableStateOf(false) }
    var commentsFor by remember { mutableStateOf<FeedPost?>(null) }
    val dark = isDarkTheme()
    val primary = MaterialTheme.colorScheme.onBackground

    fun finish(reason: String) {
        if (finished) return
        finished = true
        tracker.close() // final empty frame before step_end
        onDone(reason)
    }

    // Absolute scroll offset: heights of the items above the first visible one
    // (all measured already, since the feed is scrolled from the top) plus the offset into it.
    val heights = remember { HashMap<Int, Int>() }
    tracker.scrollY = {
        listState.layoutInfo.visibleItemsInfo.forEach { heights[it.index] = it.size }
        val first = listState.firstVisibleItemIndex
        ((0 until first).sumOf { heights[it] ?: 0 } + listState.firstVisibleItemScrollOffset).toFloat()
    }

    LaunchedEffect(Unit) {
        while (true) withFrameNanos { tracker.vsyncNs = Clocks.fromMonotonic(it) }
    }
    DisposableEffect(view) {
        val loc = IntArray(2)
        val listener = ViewTreeObserver.OnDrawListener {
            if (finished) return@OnDrawListener
            view.getLocationOnScreen(loc)
            tracker.onDraw(loc[0].toFloat(), loc[1].toFloat())
        }
        view.viewTreeObserver.addOnDrawListener(listener)
        onDispose {
            view.viewTreeObserver.removeOnDrawListener(listener)
            if (!finished) tracker.close()
        }
    }

    var showDone by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        delay(((cfg.doneButtonAfterS ?: 0.0) * 1000).toLong())
        showDone = true
        log.event("done_button_shown")
    }
    cfg.timeLimitS?.let { limit ->
        LaunchedEffect(Unit) {
            delay((limit * 1000).toLong())
            finish("time_limit")
        }
    }

    Box(Modifier.fillMaxSize()) {
    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
        // Blank strip where the status bar would be, so the sync patch doesn't cover the wordmark.
        val sync = pkg.study.display.syncPatch
        if (sync.enabled) Spacer(Modifier.height(maxOf(24, sync.sizeDp + 16).dp))

        // top bar: wordmark, notifications, messages
        Row(
            Modifier.fillMaxWidth().height(52.dp).padding(start = 14.dp, end = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(pkg.study.platform.name, fontFamily = Wordmark, fontSize = 32.sp, color = primary,
                modifier = Modifier.offset(y = 2.dp))
            Icon(FeedIcons.ChevronDown, null, tint = primary, modifier = Modifier.padding(start = 2.dp).size(16.dp))
            Spacer(Modifier.weight(1f))
            // In the top bar rather than over the feed, so it never covers a post.
            if (showDone) {
                Button(
                    onClick = { finish("done_button") },
                    colors = ButtonDefaults.buttonColors(containerColor = FeedColors.Blue, contentColor = Color.White),
                    shape = RoundedCornerShape(8.dp),
                    contentPadding = PaddingValues(horizontal = 14.dp, vertical = 0.dp),
                    modifier = Modifier.height(32.dp).padding(end = 4.dp),
                ) { Text("I'm done", fontWeight = FontWeight.SemiBold, fontSize = 14.sp) }
            }
            BarIcon(FeedIcons.Heart)
            BarIcon(FeedIcons.Messages)
        }

        Box(Modifier.weight(1f)) {
            LazyColumn(
                state = listState,
                modifier = Modifier
                    .fillMaxSize()
                    .onGloballyPositioned { c ->
                        val p = c.positionInWindow()
                        val area = ScreenRect(p.x, p.y, p.x + c.size.width, p.y + c.size.height)
                        if (tracker.feedArea != area) {
                            tracker.feedArea = area
                            val loc = IntArray(2).also(view::getLocationOnScreen)
                            log.setMeta("feed_area", area.offset(loc[0].toFloat(), loc[1].toFloat()).toJson())
                        }
                    },
            ) {
                item(key = "stories") { StoriesTray(pkg, session.plan.feed) }
                items(session.plan.feed, key = { it.postId }) { post ->
                    DisposableEffect(post.postId) { onDispose { tracker.remove(post.postId) } }
                    PostCard(
                        post = post,
                        pkg = pkg,
                        imageMaxWidth = imageMaxWidth,
                        allowLikes = cfg.allowLikes,
                        track = { element, coords -> tracker.update(post.postId, element, coords) },
                        event = { type, fields -> log.event(type, fields = arrayOf("post_id" to post.postId, *fields)) },
                        onOpenComments = {
                            commentsFor = post
                            log.event("comments_open", fields = arrayOf("post_id" to post.postId))
                        },
                    )
                }
                item(key = "end_of_feed") { CaughtUp(dark) }
            }
        }

        HorizontalDivider(thickness = 0.5.dp, color = FeedColors.divider(dark))
        // Tab bar, for the look only: the tabs do nothing.
        Row(
            Modifier.fillMaxWidth().height(50.dp),
            horizontalArrangement = Arrangement.SpaceAround,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            BarIcon(FeedIcons.HomeFilled)
            BarIcon(FeedIcons.Search)
            BarIcon(FeedIcons.Create)
            BarIcon(FeedIcons.Reels)
            Box(
                Modifier.size(26.dp).border(1.5.dp, primary, CircleShape).padding(3.dp)
                    .background(MaterialTheme.colorScheme.surfaceVariant, CircleShape),
            )
        }
    }

    // Comments sheet. Drawn in this window rather than as a dialog, so the system
    // bars stay hidden and the feed doesn't move when it opens.
    fun closeComments() {
        commentsFor?.let { log.event("comments_close", fields = arrayOf("post_id" to it.postId)) }
        commentsFor = null
    }
    BackHandler(enabled = commentsFor != null) { closeComments() }
    var sheetPost by remember { mutableStateOf<FeedPost?>(null) } // kept during the exit animation
    if (commentsFor != null) sheetPost = commentsFor
    AnimatedVisibility(commentsFor != null, enter = fadeIn(), exit = fadeOut()) {
        Box(
            Modifier.fillMaxSize().background(Color(0x66000000)).clickable(
                interactionSource = remember { MutableInteractionSource() }, indication = null,
            ) { closeComments() },
        )
    }
    AnimatedVisibility(
        commentsFor != null,
        enter = slideInVertically { it },
        exit = slideOutVertically { it },
        modifier = Modifier.align(Alignment.BottomCenter),
    ) {
        var drag by remember { mutableStateOf(0f) }
        Column(
            Modifier
                .fillMaxWidth()
                .heightIn(max = (LocalConfiguration.current.screenHeightDp * 0.72f).dp)
                .offset { IntOffset(0, drag.roundToInt().coerceAtLeast(0)) }
                .background(MaterialTheme.colorScheme.background, RoundedCornerShape(topStart = 16.dp, topEnd = 16.dp))
                .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) {},
        ) {
            Box(
                Modifier.fillMaxWidth().height(28.dp).pointerInput(Unit) {
                    detectVerticalDragGestures(
                        onDragEnd = { if (drag > 150f) closeComments(); drag = 0f },
                        onDragCancel = { drag = 0f },
                    ) { _, dy -> drag += dy }
                },
                contentAlignment = Alignment.Center,
            ) {
                Box(Modifier.size(width = 36.dp, height = 4.dp).background(FeedColors.secondary(dark), RoundedCornerShape(2.dp)))
            }
            sheetPost?.let { Column(Modifier.verticalScroll(rememberScrollState())) { CommentsSheet(pkg, it, dark) } }
        }
    }
    }
}

@Composable
private fun BarIcon(icon: ImageVector) {
    Box(Modifier.size(44.dp), contentAlignment = Alignment.Center) {
        Icon(icon, null, tint = MaterialTheme.colorScheme.onBackground, modifier = Modifier.size(26.dp))
    }
}

/**
 * Story circles across the top of the feed: "Your story", then the accounts in
 * the feed. For the look only; tapping does nothing (the touch is still in touch.csv).
 */
@Composable
private fun StoriesTray(pkg: StudyPackage, feed: List<FeedPost>) {
    val accounts = remember(feed) { feed.map { it.accountId }.distinct() }
    val ring = storyRing()
    LazyRow(
        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        item {
            StoryBubble("Your story") {
                Box {
                    Box(Modifier.size(68.dp).padding(3.dp).background(MaterialTheme.colorScheme.surfaceVariant, CircleShape))
                    Box(
                        Modifier.align(Alignment.BottomEnd).size(22.dp)
                            .border(2.dp, MaterialTheme.colorScheme.background, CircleShape)
                            .background(FeedColors.Blue, CircleShape),
                        contentAlignment = Alignment.Center,
                    ) { Icon(FeedIcons.Plus, null, tint = Color.White, modifier = Modifier.size(16.dp)) }
                }
            }
        }
        items(accounts) { id ->
            val account = pkg.manifest.accounts.getValue(id)
            StoryBubble(account.handle) {
                Box(Modifier.size(68.dp).border(2.dp, ring, CircleShape).padding(4.dp)) {
                    Avatar(pkg.file(account.avatar), 60.dp)
                }
            }
        }
    }
}

/** The story ring gradient: yellow at the bottom left to purple at the top right. */
private fun storyRing() = Brush.linearGradient(
    FeedColors.StoryRing,
    start = Offset(0f, Float.POSITIVE_INFINITY),
    end = Offset(Float.POSITIVE_INFINITY, 0f),
)

@Composable
private fun StoryBubble(name: String, circle: @Composable () -> Unit) {
    Column(Modifier.width(76.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        circle()
        Spacer(Modifier.height(4.dp))
        Text(name, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
            color = MaterialTheme.colorScheme.onBackground)
    }
}

@Composable
private fun CaughtUp(dark: Boolean) {
    val ring = storyRing()
    Column(
        Modifier.fillMaxWidth().padding(top = 24.dp, bottom = 96.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(Modifier.size(64.dp).border(2.dp, ring, CircleShape), contentAlignment = Alignment.Center) {
            Text("✓", fontSize = 30.sp, color = FeedColors.StoryRing[2])
        }
        Spacer(Modifier.height(12.dp))
        Text("You're all caught up", fontSize = 18.sp, color = MaterialTheme.colorScheme.onBackground)
        Spacer(Modifier.height(4.dp))
        Text("You've seen all new posts.", fontSize = 14.sp, color = FeedColors.secondary(dark), textAlign = TextAlign.Center)
    }
}

/** All comments of a post, opened from the comment icon or "View all N comments". */
@Composable
private fun CommentsSheet(pkg: StudyPackage, post: FeedPost, dark: Boolean) {
    val secondary = FeedColors.secondary(dark)
    Column(Modifier.fillMaxWidth().padding(bottom = 24.dp)) {
        Text("Comments", fontWeight = FontWeight.SemiBold, fontSize = 16.sp, textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onBackground, modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp))
        HorizontalDivider(thickness = 0.5.dp, color = FeedColors.divider(dark))
        if (post.comments.isEmpty()) {
            Column(Modifier.fillMaxWidth().padding(vertical = 48.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Text("No comments yet", fontSize = 22.sp, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onBackground)
                Spacer(Modifier.height(6.dp))
                Text("Start the conversation.", fontSize = 14.sp, color = secondary)
            }
        }
        for (c in post.comments) {
            val account = pkg.manifest.accounts[c.accountId]
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp)) {
                if (account != null) Avatar(pkg.file(account.avatar), 34.dp) else Spacer(Modifier.size(34.dp))
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(pkg.handle(c), fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onBackground)
                    Text(c.text, fontSize = 14.sp, color = MaterialTheme.colorScheme.onBackground)
                    Text("Reply", fontSize = 12.sp, color = secondary, fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.padding(top = 4.dp))
                }
                Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.padding(start = 8.dp, top = 4.dp)) {
                    Icon(FeedIcons.Heart, null, tint = secondary, modifier = Modifier.size(14.dp))
                    if (c.likeCount > 0) Text("${c.likeCount}", fontSize = 11.sp, color = secondary)
                }
            }
        }
    }
}
