package org.socialeyes.pictogram.ui

import android.media.MediaMetadataRetriever
import android.net.Uri
import android.view.ViewGroup
import androidx.activity.compose.BackHandler
import androidx.annotation.OptIn
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.pager.VerticalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.VolumeOff
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.outlined.CameraAlt
import androidx.compose.material.icons.outlined.MusicNote
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshots.SnapshotStateMap
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.socialeyes.pictogram.log.Clocks
import org.socialeyes.pictogram.study.ReelItem
import org.socialeyes.pictogram.study.StudyPackage
import java.io.File

/**
 * The Reels tab: full-screen vertical videos, swiped up and down. Each reel loops,
 * muted until the participant taps (tap = mute/unmute, hold = pause, double-tap =
 * like); the right-hand column has like, comment, send and more.
 *
 * Logs (via [event]): `reel_start` / `reel_end` (watched time, loops, how it ended),
 * `reel_like`, `reel_share`, `reel_mute`, `reel_pause` / `reel_resume`; every drawn
 * frame the reel's playback position goes to [videoRow] (video.csv) and the video's
 * screen rectangle to [track] (viewport.csv, element `reel`), so gaze can be mapped
 * to video frames.
 */
@OptIn(UnstableApi::class)
@Composable
fun ReelsScreen(
    pkg: StudyPackage,
    reels: List<ReelItem>,
    topInset: Dp,
    allowLikes: Boolean,
    allowShares: Boolean,
    reelLikes: SnapshotStateMap<String, Boolean>,
    track: (reelId: String, LayoutCoordinates) -> Unit,
    untrack: (reelId: String) -> Unit,
    event: (type: String, fields: Array<Pair<String, Any?>>) -> Unit,
    videoRow: (tNs: Long, reelId: String, positionMs: Long, playing: Boolean) -> Unit,
    onClose: (reason: String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val pager = rememberPagerState { reels.size }
    var muted by remember { mutableStateOf(true) }
    var held by remember { mutableStateOf(false) }
    var loops by remember { mutableIntStateOf(0) }
    var startedNs by remember { mutableLongStateOf(0L) }
    var current by remember { mutableStateOf<ReelItem?>(null) }
    var toast by remember { mutableStateOf<Pair<String, Long>?>(null) }
    var muteHint by remember { mutableStateOf<Pair<Boolean, Long>?>(null) }

    val player = remember {
        ExoPlayer.Builder(context).build().apply {
            repeatMode = Player.REPEAT_MODE_ONE
            volume = 0f
            addListener(object : Player.Listener {
                override fun onPositionDiscontinuity(old: Player.PositionInfo, new: Player.PositionInfo, reason: Int) {
                    if (reason == Player.DISCONTINUITY_REASON_AUTO_TRANSITION) loops++
                }
            })
        }
    }

    fun endCurrent(reason: String) {
        val reel = current ?: return
        event(
            "reel_end", arrayOf(
                "reel_id" to reel.reelId, "reason" to reason,
                "watched_ms" to (Clocks.elapsedNs() - startedNs) / 1_000_000, "loops" to loops,
            )
        )
        current = null
    }

    fun close(reason: String) {
        endCurrent(reason)
        onClose(reason)
    }

    // play the reel the pager settles on
    LaunchedEffect(pager.settledPage) {
        val reel = reels[pager.settledPage]
        if (current?.reelId == reel.reelId) return@LaunchedEffect
        endCurrent(if (current == null) "open" else "swipe")
        player.setMediaItem(MediaItem.fromUri(Uri.fromFile(pkg.file(reel.file))))
        player.prepare()
        player.play()
        loops = 0
        startedNs = Clocks.elapsedNs()
        current = reel
        event("reel_start", arrayOf("reel_id" to reel.reelId, "account_id" to reel.accountId))
    }

    // the playback position on every drawn frame (video.csv)
    LaunchedEffect(Unit) {
        while (true) withFrameNanos { frameNs ->
            current?.let { videoRow(Clocks.fromMonotonic(frameNs), it.reelId, player.currentPosition, player.isPlaying) }
        }
    }

    // pause in the background; release the player when the reels screen closes
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, e ->
            when (e) {
                Lifecycle.Event.ON_PAUSE -> player.pause()
                Lifecycle.Event.ON_RESUME -> if (!held) player.play()
                else -> {}
            }
        }
        lifecycle.addObserver(observer)
        onDispose {
            lifecycle.removeObserver(observer)
            endCurrent("closed") // e.g. the Home tab; no-op if already logged
            player.release()
        }
    }

    BackHandler { close("back") }

    Box(modifier.fillMaxSize().background(Color.Black)) {
        VerticalPager(state = pager, modifier = Modifier.fillMaxSize(), key = { reels[it].reelId }) { page ->
            val reel = reels[page]
            val liked = reelLikes[reel.reelId] == true
            val bigHeart = remember { Animatable(0f) }
            val bounce = remember { Animatable(1f) }

            fun setLiked(value: Boolean, via: String) {
                if (!allowLikes || liked == value) return
                reelLikes[reel.reelId] = value
                event("reel_like", arrayOf("reel_id" to reel.reelId, "liked" to value, "via" to via))
                if (value) scope.launch {
                    bounce.snapTo(0.7f)
                    bounce.animateTo(1f, spring(dampingRatio = Spring.DampingRatioMediumBouncy, stiffness = Spring.StiffnessMedium))
                }
            }

            Box(
                Modifier
                    .fillMaxSize()
                    .pointerInput(reel.reelId) {
                        detectTapGestures(
                            onPress = {
                                val pauseJob = scope.launch {
                                    delay(300) // a hold, not a tap
                                    if (page == pager.settledPage) {
                                        held = true
                                        player.pause()
                                        event("reel_pause", arrayOf("reel_id" to reel.reelId, "position_ms" to player.currentPosition))
                                    }
                                }
                                tryAwaitRelease()
                                pauseJob.cancel()
                                if (held) {
                                    held = false
                                    player.play()
                                    event("reel_resume", arrayOf("reel_id" to reel.reelId, "position_ms" to player.currentPosition))
                                }
                            },
                            onLongPress = {}, // releasing a hold must not count as a tap
                            onTap = {
                                muted = !muted
                                player.volume = if (muted) 0f else 1f
                                muteHint = muted to System.nanoTime()
                                event("reel_mute", arrayOf("reel_id" to reel.reelId, "muted" to muted))
                            },
                            onDoubleTap = {
                                if (allowLikes) {
                                    setLiked(true, "double_tap")
                                    scope.launch {
                                        bigHeart.snapTo(0.01f)
                                        bigHeart.animateTo(1f, spring(dampingRatio = 0.45f, stiffness = 600f))
                                        bigHeart.animateTo(0f, tween(250, delayMillis = 350))
                                    }
                                }
                            },
                        )
                    },
                contentAlignment = Alignment.Center,
            ) {
                // the video, whole and at its own aspect ratio, so gaze maps to video pixels
                DisposableEffect(reel.reelId) { onDispose { untrack(reel.reelId) } }
                Box(
                    Modifier
                        .aspectRatio(reel.width.toFloat() / reel.height)
                        .onGloballyPositioned { track(reel.reelId, it) },
                ) {
                    val thumb by rememberVideoThumbnail(pkg.file(reel.file))
                    thumb?.let { Image(it, null, Modifier.fillMaxSize(), contentScale = ContentScale.FillBounds) }
                    if (page == pager.settledPage) {
                        AndroidView(
                            factory = { ctx ->
                                PlayerView(ctx).apply {
                                    useController = false
                                    resizeMode = AspectRatioFrameLayout.RESIZE_MODE_FILL
                                    setShutterBackgroundColor(android.graphics.Color.TRANSPARENT)
                                    layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
                                }
                            },
                            update = { it.player = player },
                            onRelease = { it.player = null },
                            modifier = Modifier.fillMaxSize(),
                        )
                    }
                }

                if (bigHeart.value > 0f) {
                    Icon(
                        FeedIcons.HeartFilled, null, tint = Color.White,
                        modifier = Modifier.size(110.dp).scale(bigHeart.value),
                    )
                }

                ReelOverlay(
                    pkg = pkg,
                    reel = reel,
                    liked = liked,
                    likeScale = bounce.value,
                    onLike = { setLiked(!liked, "button") },
                    onShare = {
                        if (allowShares) {
                            event("reel_share", arrayOf("reel_id" to reel.reelId))
                            toast = "Sent" to System.nanoTime()
                        }
                    },
                )
            }
        }

        // top bar
        Row(
            Modifier.align(Alignment.TopStart).fillMaxWidth().padding(top = topInset).padding(horizontal = 16.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Reels", color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.weight(1f))
            Icon(Icons.Outlined.CameraAlt, null, tint = Color.White, modifier = Modifier.size(26.dp))
        }

        // mute / unmute hint
        muteHint?.let { (isMuted, id) ->
            LaunchedEffect(id) { delay(700); muteHint = null }
            Box(
                Modifier.align(Alignment.Center).size(72.dp).background(Color(0x99000000), RoundedCornerShape(36.dp)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    if (isMuted) Icons.AutoMirrored.Filled.VolumeOff else Icons.AutoMirrored.Filled.VolumeUp,
                    if (isMuted) "muted" else "sound on", tint = Color.White, modifier = Modifier.size(34.dp),
                )
            }
        }

        toast?.let { (text, id) ->
            LaunchedEffect(id) { delay(1500); toast = null }
            Box(
                Modifier.align(Alignment.BottomCenter).padding(bottom = 140.dp)
                    .background(Color(0xE6262626), RoundedCornerShape(8.dp))
                    .padding(horizontal = 18.dp, vertical = 10.dp),
            ) { Text(text, color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.SemiBold) }
        }
    }
}

/** Right-hand actions and the account, caption and audio at the bottom left. */
@Composable
private fun ReelOverlay(
    pkg: StudyPackage,
    reel: ReelItem,
    liked: Boolean,
    likeScale: Float,
    onLike: () -> Unit,
    onShare: () -> Unit,
) {
    val account = pkg.manifest.accounts[reel.accountId]
    val quiet = remember { MutableInteractionSource() }
    Box(Modifier.fillMaxSize()) {
        // soft shade behind the white text, as in the app (does not move the video)
        Box(Modifier.align(Alignment.TopCenter).fillMaxWidth().height(150.dp)
            .background(Brush.verticalGradient(listOf(Color(0x73000000), Color.Transparent))))
        Box(Modifier.align(Alignment.BottomCenter).fillMaxWidth().height(280.dp)
            .background(Brush.verticalGradient(listOf(Color.Transparent, Color(0x8C000000)))))
        Column(
            Modifier.align(Alignment.BottomEnd).padding(end = 10.dp, bottom = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(20.dp),
        ) {
            ReelAction(
                if (liked) FeedIcons.HeartFilled else FeedIcons.Heart,
                compactCount(reel.likeCount + if (liked) 1 else 0),
                tint = if (liked) FeedColors.LikeRed else Color.White,
                iconModifier = Modifier.scale(likeScale),
                modifier = Modifier.clickable(interactionSource = quiet, indication = null, onClick = onLike),
            )
            ReelAction(FeedIcons.Comment, null, modifier = Modifier)
            ReelAction(FeedIcons.Share, null, modifier = Modifier.clickable(interactionSource = quiet, indication = null, onClick = onShare))
            Icon(FeedIcons.MoreVertical, null, tint = Color.White, modifier = Modifier.size(24.dp))
        }
        Column(
            Modifier.align(Alignment.BottomStart).fillMaxWidth(0.78f).padding(start = 14.dp, bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (account != null) Avatar(pkg.file(account.avatar), 32.dp)
                Spacer(Modifier.width(10.dp))
                Text(account?.handle ?: reel.accountId, color = Color.White, fontWeight = FontWeight.SemiBold, fontSize = 14.sp,
                    maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                Spacer(Modifier.width(10.dp))
                Box(
                    Modifier.border(1.dp, Color.White, RoundedCornerShape(8.dp)).padding(horizontal = 10.dp, vertical = 4.dp),
                ) { Text("Follow", color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.SemiBold) }
            }
            if (!reel.caption.isNullOrBlank()) {
                Text(reel.caption, color = Color.White, fontSize = 14.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
            reel.audio?.takeIf { it.isNotBlank() }?.let {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Outlined.MusicNote, null, tint = Color.White, modifier = Modifier.size(14.dp))
                    Spacer(Modifier.width(6.dp))
                    Text(it, color = Color.White, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
        }
    }
}

@Composable
private fun ReelAction(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String?,
    modifier: Modifier,
    tint: Color = Color.White,
    iconModifier: Modifier = Modifier,
) {
    Column(modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        Icon(icon, null, tint = tint, modifier = iconModifier.size(30.dp))
        if (label != null) {
            Spacer(Modifier.height(4.dp))
            Text(label, color = Color.White, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
        }
    }
}

/** 3204 -> "3,204"; 15300 -> "15.3K"; 1200000 -> "1.2M", as on the app's counters. */
private fun compactCount(n: Int): String = when {
    n >= 1_000_000 -> "%.1fM".format(n / 1_000_000.0).replace(".0M", "M")
    n >= 10_000 -> "%.1fK".format(n / 1_000.0).replace(".0K", "K")
    else -> "%,d".format(n)
}

/** First frame of a video, shown for reels that aren't playing (e.g. while swiping). */
@Composable
private fun rememberVideoThumbnail(file: File) = produceState<ImageBitmap?>(null, file) {
    value = withContext(Dispatchers.IO) {
        runCatching {
            MediaMetadataRetriever().run {
                try {
                    setDataSource(file.path)
                    getFrameAtTime(0)?.asImageBitmap()
                } finally {
                    release()
                }
            }
        }.getOrNull()
    }
}
