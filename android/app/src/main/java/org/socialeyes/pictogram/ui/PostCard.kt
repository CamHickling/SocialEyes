package org.socialeyes.pictogram.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.MoreHoriz
import androidx.compose.material.icons.outlined.BookmarkBorder
import androidx.compose.material.icons.outlined.ChatBubbleOutline
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import org.socialeyes.pictogram.study.FeedPost
import org.socialeyes.pictogram.study.StudyPackage

private val VerifiedBlue = Color(0xFF3897F0)
private val LikeRed = Color(0xFFED4956)

/**
 * One feed post. Every logged part reports its position through [track] with the
 * element names of viewport.csv: post, header, image, label, actions, caption, comments.
 *
 * The image is always shown whole at its own aspect ratio (never cropped), so a
 * point in the `image` rectangle maps linearly to image pixels and AOIs.
 */
@Composable
fun PostCard(
    post: FeedPost,
    pkg: StudyPackage,
    imageMaxWidth: Int,
    allowLikes: Boolean,
    track: (element: String, LayoutCoordinates) -> Unit,
    event: (type: String, fields: Array<Pair<String, Any?>>) -> Unit,
) {
    val account = pkg.manifest.accounts.getValue(post.accountId)
    val image = pkg.manifest.images.getValue(post.imageId)
    val label = post.label?.let { pkg.study.labels[it] }
    val secondary = MaterialTheme.colorScheme.onSurfaceVariant

    var liked by rememberSaveable(post.postId) { mutableStateOf(false) }
    var captionExpanded by rememberSaveable(post.postId) { mutableStateOf(false) }
    val heart = remember { Animatable(0f) }
    val scope = rememberCoroutineScope()

    fun setLiked(value: Boolean, via: String) {
        if (!allowLikes || liked == value) return
        liked = value
        event("like", arrayOf("liked" to value, "via" to via))
    }

    Column(Modifier.fillMaxWidth().onGloballyPositioned { track("post", it) }) {
        // header
        Row(
            Modifier
                .fillMaxWidth()
                .height(56.dp)
                .onGloballyPositioned { track("header", it) }
                .padding(horizontal = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            val avatar by rememberImage(pkg.file(account.avatar), 256)
            Box(
                Modifier
                    .size(32.dp)
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.surfaceVariant)
                    .clickable { event("profile_tap", arrayOf("target" to "avatar")) },
            ) {
                avatar?.let { Image(it, null, Modifier.fillMaxSize(), contentScale = ContentScale.Crop) }
            }
            Spacer(Modifier.width(10.dp))
            Text(
                account.handle,
                fontWeight = FontWeight.SemiBold,
                fontSize = 14.sp,
                modifier = Modifier.clickable { event("profile_tap", arrayOf("target" to "handle")) },
            )
            if (account.verified) {
                Spacer(Modifier.width(4.dp))
                Icon(Icons.Filled.CheckCircle, "verified", tint = VerifiedBlue, modifier = Modifier.size(14.dp))
            }
            Spacer(Modifier.weight(1f))
            Icon(Icons.Filled.MoreHoriz, null, tint = MaterialTheme.colorScheme.onSurface)
        }

        // image, with a banner label on top of it
        Box(
            Modifier
                .fillMaxWidth()
                .aspectRatio(image.width.toFloat() / image.height)
                .background(MaterialTheme.colorScheme.surfaceVariant)
                .onGloballyPositioned { track("image", it) }
                .pointerInput(post.postId, allowLikes) {
                    detectTapGestures(
                        onDoubleTap = {
                            if (allowLikes) {
                                setLiked(true, "double_tap")
                                scope.launch {
                                    heart.snapTo(1f)
                                    heart.animateTo(0f, tween(700))
                                }
                            }
                        },
                        onTap = { event("image_tap", emptyArray()) },
                    )
                },
        ) {
            val bitmap by rememberImage(pkg.file(image.file), imageMaxWidth)
            bitmap?.let { Image(it, null, Modifier.fillMaxSize(), contentScale = ContentScale.FillBounds) }
            if (label != null && label.style == "banner") {
                Row(
                    Modifier
                        .align(Alignment.BottomStart)
                        .fillMaxWidth()
                        .background(Color(0xCC000000))
                        .onGloballyPositioned { track("label", it) }
                        .clickable { event("label_tap", emptyArray()) }
                        .padding(horizontal = 12.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Icon(Icons.Filled.Info, null, tint = Color.White, modifier = Modifier.size(16.dp))
                    Text(label.text, color = Color.White, fontSize = 13.sp)
                }
            }
            if (heart.value > 0f) {
                Icon(
                    Icons.Filled.Favorite, null, tint = Color.White.copy(alpha = heart.value),
                    modifier = Modifier.align(Alignment.Center).size(96.dp).scale(0.8f + 0.4f * heart.value),
                )
            }
        }

        if (label != null && label.style == "caption") {
            Text(
                label.text,
                color = secondary,
                fontSize = 12.sp,
                modifier = Modifier
                    .fillMaxWidth()
                    .onGloballyPositioned { track("label", it) }
                    .clickable { event("label_tap", emptyArray()) }
                    .padding(horizontal = 12.dp, vertical = 6.dp),
            )
        }

        // actions and like count
        Column(Modifier.fillMaxWidth().onGloballyPositioned { track("actions", it) }) {
            Row(
                Modifier.fillMaxWidth().height(48.dp).padding(horizontal = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                ActionIcon(onClick = { setLiked(!liked, "button") }) {
                    Icon(
                        if (liked) Icons.Filled.Favorite else Icons.Filled.FavoriteBorder,
                        "like",
                        tint = if (liked) LikeRed else MaterialTheme.colorScheme.onSurface,
                    )
                }
                ActionIcon(onClick = null) {
                    Icon(Icons.Outlined.ChatBubbleOutline, null, tint = MaterialTheme.colorScheme.onSurface,
                        modifier = Modifier.graphicsLayer { scaleX = -1f })
                }
                ActionIcon(onClick = null) {
                    Icon(Icons.AutoMirrored.Outlined.Send, null, tint = MaterialTheme.colorScheme.onSurface,
                        modifier = Modifier.graphicsLayer { rotationZ = -20f })
                }
                Spacer(Modifier.weight(1f))
                ActionIcon(onClick = null) {
                    Icon(Icons.Outlined.BookmarkBorder, null, tint = MaterialTheme.colorScheme.onSurface)
                }
            }
            val likes = post.likeCount + if (liked) 1 else 0
            Text(
                if (likes == 1) "1 like" else "%,d likes".format(likes),
                fontWeight = FontWeight.SemiBold,
                fontSize = 14.sp,
                modifier = Modifier.padding(horizontal = 12.dp),
            )
        }

        if (post.caption.isNotBlank()) {
            var overflowing by remember(post.postId) { mutableStateOf(false) }
            Column(
                Modifier
                    .fillMaxWidth()
                    .onGloballyPositioned { track("caption", it) }
                    .clickable(
                        enabled = overflowing && !captionExpanded,
                        interactionSource = remember { MutableInteractionSource() },
                        indication = null,
                    ) {
                        captionExpanded = true
                        event("caption_expand", emptyArray())
                    }
                    .padding(horizontal = 12.dp, vertical = 4.dp),
            ) {
                Text(
                    buildAnnotatedString {
                        withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) { append(account.handle) }
                        append(" ")
                        append(post.caption)
                    },
                    fontSize = 14.sp,
                    maxLines = if (captionExpanded) Int.MAX_VALUE else 2,
                    overflow = TextOverflow.Ellipsis,
                    onTextLayout = { if (!captionExpanded) overflowing = it.hasVisualOverflow },
                )
                if (overflowing && !captionExpanded) Text("more", color = secondary, fontSize = 14.sp)
            }
        }

        if (post.comments.isNotEmpty()) {
            Column(
                Modifier
                    .fillMaxWidth()
                    .onGloballyPositioned { track("comments", it) }
                    .padding(horizontal = 12.dp, vertical = 2.dp),
            ) {
                for (c in post.comments) {
                    val handle = pkg.manifest.accounts[c.accountId]?.handle ?: c.accountId
                    Text(
                        buildAnnotatedString {
                            withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) { append(handle) }
                            append(" ")
                            append(c.text)
                        },
                        fontSize = 14.sp,
                        modifier = Modifier.padding(vertical = 2.dp),
                    )
                }
            }
        }
        post.postedAgo?.takeIf { it.isNotBlank() }?.let {
            Text(it, color = secondary, fontSize = 12.sp, modifier = Modifier.padding(horizontal = 12.dp, vertical = 4.dp))
        }
        Spacer(Modifier.height(12.dp))
    }
}

@Composable
private fun ActionIcon(onClick: (() -> Unit)?, content: @Composable () -> Unit) {
    Box(
        Modifier
            .size(44.dp)
            .clip(CircleShape)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier),
        contentAlignment = Alignment.Center,
    ) { content() }
}
