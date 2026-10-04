package org.socialeyes.pictogram.ui

import android.view.ViewTreeObserver
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
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
import androidx.compose.foundation.lazy.itemsIndexed
import org.socialeyes.pictogram.study.StoryItem
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
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.rememberCoroutineScope
import kotlinx.coroutines.launch
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
    val commentLikes = remember { mutableStateMapOf<String, Boolean>() }
    val ownComments = remember { mutableStateMapOf<String, List<OwnComment>>() } // post_id -> comments
    var ownCount by remember { mutableIntStateOf(0) }
    var draftStartNs by remember { mutableStateOf<Long?>(null) }
    // stories: grouped by account in stories.csv order; which have been seen; which account is open
    val storyGroups = remember { pkg.manifest.stories.groupBy { it.accountId }.values.toList() }
    val seenStories = remember { mutableStateMapOf<String, Boolean>() }
    val storyLikes = remember { mutableStateMapOf<String, Boolean>() }
    var openStoryGroup by remember { mutableStateOf<Int?>(null) }
    // Reels tab
    var reelsOpen by remember { mutableStateOf(false) }
    val reelLikes = remember { mutableStateMapOf<String, Boolean>() }
    var toast by remember { mutableStateOf<Pair<String, Long>?>(null) } // text, id
    val scope = rememberCoroutineScope()
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
            tracker.windowSize = view.width.toFloat() to view.height.toFloat()
            tracker.onDraw(loc[0].toFloat(), loc[1].toFloat())
        }
        view.viewTreeObserver.addOnDrawListener(listener)
        onDispose {
            view.viewTreeObserver.removeOnDrawListener(listener)
            if (!finished) tracker.close()
        }
    }

    var showDone by remember { mutableStateOf(false) }
    cfg.doneButtonAfterS?.let { after -> // null: no done button
        LaunchedEffect(Unit) {
            delay((after * 1000).toLong())
            showDone = true
            log.event("done_button_shown")
        }
    }
    cfg.timeLimitS?.let { limit ->
        LaunchedEffect(Unit) {
            delay((limit * 1000).toLong())
            finish("time_limit")
        }
    }

    // Blank strip where the status bar would be, so the sync patch doesn't cover the wordmark.
    val sync = pkg.study.display.syncPatch
    val topStrip = if (sync.enabled) maxOf(24, sync.sizeDp + 16).dp else 0.dp

    Box(Modifier.fillMaxSize()) {
    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
        if (topStrip > 0.dp) Spacer(Modifier.height(topStrip))

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
                item(key = "stories") {
                    StoriesTray(pkg, session.plan.feed, storyGroups, seenStories) { g ->
                        log.event("story_open", fields = arrayOf("account_id" to storyGroups[g].first().accountId))
                        openStoryGroup = g
                    }
                }
                items(session.plan.feed, key = { it.postId }) { post ->
                    DisposableEffect(post.postId) { onDispose { tracker.remove(post.postId) } }
                    PostCard(
                        post = post,
                        pkg = pkg,
                        imageMaxWidth = imageMaxWidth,
                        allowLikes = cfg.allowLikes,
                        allowSaves = cfg.allowSaves,
                        allowShares = cfg.allowShares,
                        onShared = { toast = "Sent" to System.nanoTime() },
                        participantHandle = pkg.study.platform.participantHandle,
                        ownComments = ownComments[post.postId].orEmpty(),
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

        // the tab bar turns dark while Reels is open, as in the app
        val barTint = if (reelsOpen) Color.White else MaterialTheme.colorScheme.onBackground
        HorizontalDivider(thickness = 0.5.dp, color = if (reelsOpen) Color(0xFF262626) else FeedColors.divider(dark))
        // Tab bar. Home scrolls back to the top of the feed; the other tabs are for the look only.
        Row(
            Modifier.fillMaxWidth().height(50.dp).background(if (reelsOpen) Color.Black else MaterialTheme.colorScheme.background),
            horizontalArrangement = Arrangement.SpaceAround,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            BarIcon(FeedIcons.HomeFilled, barTint) {
                if (reelsOpen) {
                    reelsOpen = false // ReelsScreen logs reel_end on close via onClose
                    log.event("reels_close", fields = arrayOf("reason" to "home_tab"))
                    tracker.clearOverlay()
                } else {
                    log.event("home_tap")
                    scope.launch { listState.animateScrollToItem(0) }
                }
            }
            BarIcon(FeedIcons.Search, barTint)
            BarIcon(FeedIcons.Create, barTint)
            BarIcon(FeedIcons.Reels, barTint) {
                if (!reelsOpen && pkg.manifest.reels.isNotEmpty()) {
                    log.event("reels_open")
                    reelsOpen = true
                }
            }
            Box(Modifier.size(44.dp), contentAlignment = Alignment.Center) { ParticipantAvatar(27.dp, dark) }
        }
    }

    // Reels: over everything but the tab bar
    if (reelsOpen) {
        ReelsScreen(
            pkg = pkg,
            reels = pkg.manifest.reels,
            topInset = topStrip,
            allowLikes = cfg.allowLikes,
            allowShares = cfg.allowShares,
            reelLikes = reelLikes,
            track = { reelId, coords -> tracker.updateOverlay(reelId, "reel", coords) },
            untrack = { reelId -> tracker.removeOverlay(reelId, "reel") },
            event = { type, fields -> log.event(type, fields = fields) },
            videoRow = log::videoRow,
            onClose = { reason ->
                if (reelsOpen) log.event("reels_close", fields = arrayOf("reason" to reason))
                reelsOpen = false
                tracker.clearOverlay()
            },
            modifier = Modifier.padding(bottom = 50.5.dp), // the tab bar stays visible
        )
    }

    // "Sent" confirmation, like the app's own short pop-ups.
    toast?.let { (text, id) ->
        LaunchedEffect(id) {
            delay(1500)
            toast = null
        }
        Box(
            Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = 72.dp)
                .background(Color(0xE6262626), RoundedCornerShape(8.dp))
                .padding(horizontal = 18.dp, vertical = 10.dp),
        ) { Text(text, color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.SemiBold) }
    }

    openStoryGroup?.let { g ->
        StoryViewer(
            pkg = pkg,
            groups = storyGroups,
            startGroup = g,
            topInset = topStrip,
            track = { storyId, coords -> tracker.updateOverlay(storyId, "story", coords) },
            untrack = { storyId -> tracker.removeOverlay(storyId, "story") },
            event = { type, fields -> log.event(type, fields = fields) },
            onSeen = { seenStories[it] = true },
            allowReplies = cfg.allowCommentTyping,
            allowLikes = cfg.allowLikes,
            allowShares = cfg.allowShares,
            storyLikes = storyLikes,
            onClose = { reason ->
                log.event("story_close", fields = arrayOf("reason" to reason))
                tracker.clearOverlay()
                openStoryGroup = null
            },
        )
    }

    commentsFor?.let { post ->
        key(post.postId) {
            CommentsSheet(
                pkg = pkg,
                post = post,
                topInset = topStrip,
                allowCommentLikes = cfg.allowCommentLikes,
                allowTyping = cfg.allowCommentTyping,
                participantHandle = pkg.study.platform.participantHandle,
                ownComments = ownComments[post.postId].orEmpty(),
                commentLikes = commentLikes,
                track = { element, coords -> tracker.updateOverlay(post.postId, element, coords) },
                trackClip = tracker::setOverlayClip,
                onCommentLike = { id, liked ->
                    // study comments by position (0, 1, ...), the participant's own as p1, p2, ...
                    log.event("comment_like", fields = arrayOf("post_id" to post.postId, "comment" to (id.toIntOrNull() ?: id), "liked" to liked))
                },
                onDraftChange = { text, replyTo ->
                    if (draftStartNs == null && text.isNotEmpty()) draftStartNs = Clocks.elapsedNs()
                    log.event("comment_edit", fields = arrayOf("post_id" to post.postId, "text" to text, "reply_to" to replyTo?.let { it.toIntOrNull() ?: it }))
                },
                onSubmit = { text, replyTo, thread ->
                    ownCount++
                    val id = "p$ownCount"
                    ownComments[post.postId] = ownComments[post.postId].orEmpty() + OwnComment(id, text, replyTo, thread)
                    val typingMs = draftStartNs?.let { (Clocks.elapsedNs() - it) / 1_000_000 }
                    draftStartNs = null
                    log.event(
                        "comment_submit", fields = arrayOf(
                            "post_id" to post.postId, "comment_id" to id, "text" to text,
                            "reply_to" to replyTo?.let { it.toIntOrNull() ?: it }, "typing_ms" to typingMs,
                        )
                    )
                },
                onState = { state ->
                    log.event("comments_sheet", fields = arrayOf("post_id" to post.postId, "state" to state.name.lowercase()))
                },
                onClose = {
                    draftStartNs = null
                    log.event("comments_close", fields = arrayOf("post_id" to post.postId))
                    tracker.clearOverlay()
                    commentsFor = null
                },
            )
        }
    }
    }
}

@Composable
private fun BarIcon(icon: ImageVector, tint: Color = Color.Unspecified, onClick: (() -> Unit)? = null) {
    Box(
        Modifier
            .size(44.dp)
            .then(
                if (onClick != null) {
                    Modifier.clickable(interactionSource = remember { MutableInteractionSource() }, indication = null, onClick = onClick)
                } else Modifier
            ),
        contentAlignment = Alignment.Center,
    ) {
        Icon(icon, null, tint = if (tint == Color.Unspecified) MaterialTheme.colorScheme.onBackground else tint, modifier = Modifier.size(26.dp))
    }
}

/**
 * Story circles across the top of the feed: "Your story", then the accounts in
 * the feed. For the look only; tapping does nothing (the touch is still in touch.csv).
 */
@Composable
private fun StoriesTray(
    pkg: StudyPackage,
    feed: List<FeedPost>,
    storyGroups: List<List<StoryItem>>,
    seen: Map<String, Boolean>,
    onOpen: (group: Int) -> Unit,
) {
    // With stories.csv: the accounts that have stories, and tapping opens them.
    // Without: the feed's accounts, for the look only.
    val accounts = remember(feed, storyGroups) {
        if (storyGroups.isNotEmpty()) storyGroups.map { it.first().accountId } else feed.map { it.accountId }.distinct()
    }
    val ring = storyRing()
    val seenRing = FeedColors.divider(isDarkTheme())
    LazyRow(
        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        item {
            StoryBubble("Your story") {
                Box {
                    ParticipantAvatar(62.dp, isDarkTheme(), Modifier.padding(3.dp))
                    Box(
                        Modifier.align(Alignment.BottomEnd).size(22.dp)
                            .border(2.dp, MaterialTheme.colorScheme.background, CircleShape)
                            .background(FeedColors.Blue, CircleShape),
                        contentAlignment = Alignment.Center,
                    ) { Icon(FeedIcons.Plus, null, tint = Color.White, modifier = Modifier.size(16.dp)) }
                }
            }
        }
        itemsIndexed(accounts) { g, id ->
            val account = pkg.manifest.accounts.getValue(id)
            val group = storyGroups.getOrNull(g)
            val allSeen = group != null && group.all { seen[it.storyId] == true }
            StoryBubble(
                account.handle,
                modifier = if (group != null) {
                    Modifier.clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) { onOpen(g) }
                } else Modifier,
            ) {
                Box(
                    Modifier
                        .size(68.dp)
                        .then(if (allSeen) Modifier.border(1.dp, seenRing, CircleShape) else Modifier.border(2.dp, ring, CircleShape))
                        .padding(4.dp),
                ) {
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
private fun StoryBubble(name: String, modifier: Modifier = Modifier, circle: @Composable () -> Unit) {
    Column(modifier.width(76.dp), horizontalAlignment = Alignment.CenterHorizontally) {
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
