package org.socialeyes.pictogram.ui

import android.view.ViewTreeObserver
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.outlined.AccountCircle
import androidx.compose.material.icons.outlined.AddBox
import androidx.compose.material.icons.outlined.FavoriteBorder
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.Slideshow
import androidx.compose.material3.Icon
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
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
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import org.socialeyes.pictogram.Session
import org.socialeyes.pictogram.log.Clocks
import org.socialeyes.pictogram.log.ScreenRect
import org.socialeyes.pictogram.log.ViewportTracker
import org.socialeyes.pictogram.study.Step

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

    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
        Row(
            Modifier.fillMaxWidth().height(56.dp).padding(horizontal = 16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(pkg.study.platform.name, fontFamily = FontFamily.Cursive, fontSize = 28.sp)
            Spacer(Modifier.weight(1f))
            BarIcon(Icons.Outlined.FavoriteBorder)
            Spacer(Modifier.width(20.dp))
            BarIcon(Icons.AutoMirrored.Outlined.Send)
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
                items(session.plan.feed, key = { it.postId }) { post ->
                    DisposableEffect(post.postId) { onDispose { tracker.remove(post.postId) } }
                    PostCard(
                        post = post,
                        pkg = pkg,
                        imageMaxWidth = imageMaxWidth,
                        allowLikes = cfg.allowLikes,
                        track = { element, coords -> tracker.update(post.postId, element, coords) },
                        event = { type, fields -> log.event(type, fields = arrayOf("post_id" to post.postId, *fields)) },
                    )
                }
                item(key = "end_of_feed") {
                    Text(
                        "You're all caught up",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth().padding(top = 32.dp, bottom = 120.dp),
                    )
                }
            }
            if (showDone) {
                Button(
                    onClick = { finish("done_button") },
                    modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 24.dp),
                ) { Text("I'm done") }
            }
        }
        HorizontalDivider(thickness = 0.5.dp)
        // Tab bar, for the look only: the tabs do nothing.
        Row(
            Modifier.fillMaxWidth().height(52.dp),
            horizontalArrangement = Arrangement.SpaceEvenly,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            BarIcon(Icons.Filled.Home)
            BarIcon(Icons.Outlined.Search)
            BarIcon(Icons.Outlined.AddBox)
            BarIcon(Icons.Outlined.Slideshow)
            BarIcon(Icons.Outlined.AccountCircle)
        }
    }
}

@Composable
private fun BarIcon(icon: ImageVector) =
    Icon(icon, null, tint = MaterialTheme.colorScheme.onSurface, modifier = Modifier.size(26.dp))
