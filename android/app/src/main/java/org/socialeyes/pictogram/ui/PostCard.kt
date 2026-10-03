package org.socialeyes.pictogram.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
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
import androidx.compose.material.icons.outlined.Info
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import org.socialeyes.pictogram.study.Comment
import org.socialeyes.pictogram.study.FeedPost
import org.socialeyes.pictogram.study.StudyPackage
import java.io.File

/** Comments shown under a post before "View all N comments". */
const val INLINE_COMMENTS = 2

@Composable
fun isDarkTheme() = MaterialTheme.colorScheme.background.luminance() < 0.5f

/**
 * One feed post, laid out like a post in the big photo-sharing apps. Every
 * logged part reports its position through [track] with the element names of
 * viewport.csv: post, header, image, label, actions, caption, comments.
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
    allowSaves: Boolean,
    allowShares: Boolean,
    onShared: () -> Unit,
    track: (element: String, LayoutCoordinates) -> Unit,
    event: (type: String, fields: Array<Pair<String, Any?>>) -> Unit,
    onOpenComments: () -> Unit,
) {
    val account = pkg.manifest.accounts.getValue(post.accountId)
    val image = pkg.manifest.images.getValue(post.imageId)
    val label = post.label?.let { pkg.study.labels[it] }
    val dark = isDarkTheme()
    val primary = MaterialTheme.colorScheme.onBackground
    val secondary = FeedColors.secondary(dark)

    var liked by rememberSaveable(post.postId) { mutableStateOf(false) }
    var saved by rememberSaveable(post.postId) { mutableStateOf(false) }
    val saveBounce = remember { Animatable(1f) }
    val bigHeart = remember { Animatable(0f) }
    val likeBounce = remember { Animatable(1f) }
    val scope = rememberCoroutineScope()

    fun setLiked(value: Boolean, via: String) {
        if (!allowLikes || liked == value) return
        liked = value
        event("like", arrayOf("liked" to value, "via" to via))
        if (value) scope.launch {
            likeBounce.snapTo(0.7f)
            likeBounce.animateTo(1f, spring(dampingRatio = Spring.DampingRatioMediumBouncy, stiffness = Spring.StiffnessMedium))
        }
    }

    Column(Modifier.fillMaxWidth().onGloballyPositioned { track("post", it) }) {
        // header: avatar, handle, badge, menu
        Row(
            Modifier
                .fillMaxWidth()
                .height(54.dp)
                .onGloballyPositioned { track("header", it) }
                .padding(start = 12.dp, end = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Avatar(pkg.file(account.avatar), 32.dp, Modifier.clickable { event("profile_tap", arrayOf("target" to "avatar")) })
            Spacer(Modifier.width(10.dp))
            Text(
                account.handle,
                color = primary,
                fontWeight = FontWeight.SemiBold,
                fontSize = 14.sp,
                modifier = Modifier.clickable(
                    interactionSource = remember { MutableInteractionSource() }, indication = null,
                ) { event("profile_tap", arrayOf("target" to "handle")) },
            )
            if (account.verified) {
                Spacer(Modifier.width(4.dp))
                VerifiedBadge(12.dp)
            }
            Spacer(Modifier.weight(1f))
            Box(Modifier.size(40.dp), contentAlignment = Alignment.Center) {
                Icon(FeedIcons.MoreVertical, null, tint = primary, modifier = Modifier.size(20.dp))
            }
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
                                    bigHeart.snapTo(0.01f)
                                    bigHeart.animateTo(1f, spring(dampingRatio = 0.45f, stiffness = 600f))
                                    bigHeart.animateTo(0f, tween(250, delayMillis = 350))
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
                        .background(Color(0xB3000000))
                        .onGloballyPositioned { track("label", it) }
                        .clickable { event("label_tap", emptyArray()) }
                        .padding(horizontal = 12.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Icon(Icons.Outlined.Info, null, tint = Color.White, modifier = Modifier.size(18.dp))
                    Text(label.text, color = Color.White, fontSize = 13.sp)
                }
            }
            if (bigHeart.value > 0f) {
                Icon(
                    FeedIcons.HeartFilled, null, tint = Color.White,
                    modifier = Modifier.align(Alignment.Center).size(110.dp).scale(bigHeart.value),
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
                Modifier.fillMaxWidth().height(46.dp).padding(horizontal = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                ActionIcon(
                    if (liked) FeedIcons.HeartFilled else FeedIcons.Heart,
                    tint = if (liked) FeedColors.LikeRed else primary,
                    modifier = Modifier.scale(likeBounce.value),
                ) { setLiked(!liked, "button") }
                ActionIcon(FeedIcons.Comment, primary, onClick = onOpenComments)
                ActionIcon(FeedIcons.Share, primary, onClick = if (allowShares) {
                    {
                        event("share", emptyArray())
                        onShared()
                    }
                } else null)
                Spacer(Modifier.weight(1f))
                ActionIcon(
                    if (saved) FeedIcons.BookmarkFilled else FeedIcons.Bookmark, primary,
                    modifier = Modifier.scale(saveBounce.value),
                    onClick = if (allowSaves) {
                        {
                            saved = !saved
                            event("save", arrayOf("saved" to saved))
                            if (saved) scope.launch {
                                saveBounce.snapTo(0.7f)
                                saveBounce.animateTo(1f, spring(dampingRatio = Spring.DampingRatioMediumBouncy, stiffness = Spring.StiffnessMedium))
                            }
                        }
                    } else null,
                )
            }
            val likes = post.likeCount + if (liked) 1 else 0
            if (likes > 0) {
                Text(
                    if (likes == 1) "1 like" else "%,d likes".format(likes),
                    color = primary,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 14.sp,
                    modifier = Modifier.padding(horizontal = 12.dp),
                )
            }
        }

        if (post.caption.isNotBlank()) {
            Caption(
                handle = account.handle,
                caption = post.caption,
                primary = primary,
                secondary = secondary,
                modifier = Modifier
                    .fillMaxWidth()
                    .onGloballyPositioned { track("caption", it) }
                    .padding(horizontal = 12.dp, vertical = 4.dp),
                onExpand = { event("caption_expand", emptyArray()) },
            )
        }

        if (post.comments.isNotEmpty()) {
            Column(
                Modifier
                    .fillMaxWidth()
                    .onGloballyPositioned { track("comments", it) }
                    .padding(horizontal = 12.dp),
            ) {
                if (post.comments.size > INLINE_COMMENTS) {
                    Text(
                        "View all ${post.comments.size} comments",
                        color = secondary,
                        fontSize = 14.sp,
                        modifier = Modifier
                            .padding(vertical = 2.dp)
                            .clickable(
                                interactionSource = remember { MutableInteractionSource() }, indication = null,
                                onClick = onOpenComments,
                            ),
                    )
                }
                for (c in post.comments.take(INLINE_COMMENTS)) {
                    Text(
                        handleAndText(pkg.handle(c), c.text),
                        color = primary,
                        fontSize = 14.sp,
                        modifier = Modifier.padding(vertical = 2.dp),
                    )
                }
            }
        }

        post.postedAgo?.takeIf { it.isNotBlank() }?.let {
            Text(longTimeAgo(it), color = secondary, fontSize = 12.sp, modifier = Modifier.padding(horizontal = 12.dp, vertical = 4.dp))
        }
        Spacer(Modifier.height(14.dp))
    }
}

/**
 * Caption cut to two lines with an inline "… more"; tapping it shows the rest
 * and logs `caption_expand`.
 */
@Composable
private fun Caption(
    handle: String,
    caption: String,
    primary: Color,
    secondary: Color,
    modifier: Modifier,
    onExpand: () -> Unit,
) {
    var expanded by rememberSaveable(handle, caption) { mutableStateOf(false) }
    var cut by remember(caption) { mutableStateOf<Int?>(null) } // caption characters that fit before "… more"

    fun measure(layout: TextLayoutResult) {
        if (expanded || cut != null || !layout.hasVisualOverflow) return
        val end = layout.getLineEnd(1, visibleEnd = true)
        cut = (end - handle.length - 1 - 8).coerceAtLeast(0) // leave room for "… more"
    }

    val text: AnnotatedString = if (expanded || cut == null) {
        handleAndText(handle, caption)
    } else {
        buildAnnotatedString {
            append(handleAndText(handle, caption.take(cut!!).trimEnd()))
            append("… ")
            withStyle(SpanStyle(color = secondary)) { append("more") }
        }
    }
    Text(
        text,
        color = primary,
        fontSize = 14.sp,
        lineHeight = 18.sp,
        maxLines = if (expanded) Int.MAX_VALUE else 2,
        onTextLayout = ::measure,
        modifier = modifier.then(
            if (!expanded && cut != null) {
                Modifier.clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) {
                    expanded = true
                    onExpand()
                }
            } else Modifier
        ),
    )
}

fun handleAndText(handle: String, text: String) = buildAnnotatedString {
    withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) { append(handle) }
    append(" ")
    append(text)
}

fun StudyPackage.handle(c: Comment) = manifest.accounts[c.accountId]?.handle ?: c.accountId

/** "3h" -> "3 hours ago", as under a feed post; any other text is shown as written. */
fun longTimeAgo(short: String): String {
    val m = Regex("""^(\d+)\s*([smhdw])$""").matchEntire(short.trim()) ?: return short
    val n = m.groupValues[1].toInt()
    val unit = when (m.groupValues[2]) {
        "s" -> "second"
        "m" -> "minute"
        "h" -> "hour"
        "d" -> "day"
        else -> "week"
    }
    return "$n $unit${if (n == 1) "" else "s"} ago"
}

@Composable
fun Avatar(file: File, size: Dp, modifier: Modifier = Modifier) {
    val bitmap by rememberImage(file, 256)
    Box(
        modifier
            .size(size)
            .clip(CircleShape)
            .background(MaterialTheme.colorScheme.surfaceVariant),
    ) {
        bitmap?.let { Image(it, null, Modifier.fillMaxSize(), contentScale = ContentScale.Crop) }
    }
}

@Composable
private fun ActionIcon(
    icon: ImageVector,
    tint: Color,
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)?,
) {
    Box(
        Modifier
            .size(42.dp)
            .then(
                if (onClick != null) {
                    Modifier.clickable(interactionSource = remember { MutableInteractionSource() }, indication = null, onClick = onClick)
                } else Modifier
            ),
        contentAlignment = Alignment.Center,
    ) {
        Icon(icon, null, tint = tint, modifier = modifier.size(26.dp))
    }
}
