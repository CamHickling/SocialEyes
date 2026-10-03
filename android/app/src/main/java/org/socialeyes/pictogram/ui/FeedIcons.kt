package org.socialeyes.pictogram.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathFillType
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.PathBuilder
import androidx.compose.ui.graphics.vector.path
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

/**
 * Thin-line icons in the style of the big photo-sharing apps, drawn on a 24-unit
 * grid. Our own drawings: no third-party icon artwork is copied.
 * Tint them with Icon(tint = ...).
 */
object FeedIcons {
    private const val STROKE = 1.9f

    private fun icon(name: String, block: ImageVector.Builder.() -> Unit) =
        ImageVector.Builder(name, 24.dp, 24.dp, 24f, 24f).apply(block).build()

    private fun ImageVector.Builder.line(fillType: PathFillType = PathFillType.NonZero, d: PathBuilder.() -> Unit) =
        path(
            stroke = SolidColor(Color.Black), strokeLineWidth = STROKE,
            strokeLineCap = StrokeCap.Round, strokeLineJoin = StrokeJoin.Round, pathFillType = fillType, pathBuilder = d,
        )

    private fun ImageVector.Builder.solid(fillType: PathFillType = PathFillType.NonZero, d: PathBuilder.() -> Unit) =
        path(fill = SolidColor(Color.Black), pathFillType = fillType, pathBuilder = d)

    private fun PathBuilder.heartShape() {
        moveTo(12f, 20.6f)
        curveTo(12f, 20.6f, 2.6f, 14.9f, 2.6f, 8.7f)
        curveTo(2.6f, 5.7f, 4.9f, 3.5f, 7.6f, 3.5f)
        curveTo(9.5f, 3.5f, 11.1f, 4.6f, 12f, 6.2f)
        curveTo(12.9f, 4.6f, 14.5f, 3.5f, 16.4f, 3.5f)
        curveTo(19.1f, 3.5f, 21.4f, 5.7f, 21.4f, 8.7f)
        curveTo(21.4f, 14.9f, 12f, 20.6f, 12f, 20.6f)
        close()
    }

    private fun PathBuilder.circle(cx: Float, cy: Float, r: Float) {
        moveTo(cx - r, cy)
        arcTo(r, r, 0f, false, true, cx + r, cy)
        arcTo(r, r, 0f, false, true, cx - r, cy)
        close()
    }

    private fun PathBuilder.roundRect(l: Float, t: Float, r: Float, b: Float, rad: Float) {
        moveTo(l + rad, t)
        lineTo(r - rad, t)
        arcTo(rad, rad, 0f, false, true, r, t + rad)
        lineTo(r, b - rad)
        arcTo(rad, rad, 0f, false, true, r - rad, b)
        lineTo(l + rad, b)
        arcTo(rad, rad, 0f, false, true, l, b - rad)
        lineTo(l, t + rad)
        arcTo(rad, rad, 0f, false, true, l + rad, t)
        close()
    }

    val Heart = icon("heart") { line { heartShape() } }
    val HeartFilled = icon("heart_filled") { solid { heartShape() } }

    /** Round speech bubble, tail at the bottom right. */
    val Comment = icon("comment") {
        line {
            moveTo(19.3f, 16.2f)
            arcTo(9f, 9f, 0f, true, false, 16.2f, 19.3f)
            lineTo(21.2f, 21.2f)
            close()
        }
    }

    /** Paper plane. */
    val Share = icon("share") {
        line {
            moveTo(21.5f, 3f)
            lineTo(2.5f, 9.3f)
            lineTo(9.6f, 13.2f)
            lineTo(13.5f, 21.5f)
            close()
        }
        line {
            moveTo(21.5f, 3f)
            lineTo(9.6f, 13.2f)
        }
    }

    val Bookmark = icon("bookmark") {
        line {
            moveTo(19f, 21f)
            lineTo(12f, 14.9f)
            lineTo(5f, 21f)
            lineTo(5f, 3.5f)
            lineTo(19f, 3.5f)
            close()
        }
    }

    val HomeFilled = icon("home") {
        solid(PathFillType.EvenOdd) {
            moveTo(2.5f, 10.2f)
            lineTo(12f, 2.6f)
            lineTo(21.5f, 10.2f)
            lineTo(21.5f, 21.5f)
            lineTo(2.5f, 21.5f)
            close()
            moveTo(9.4f, 21.5f)
            lineTo(9.4f, 15.3f)
            lineTo(14.6f, 15.3f)
            lineTo(14.6f, 21.5f)
            close()
        }
    }

    val Search = icon("search") {
        line { circle(10.5f, 10.5f, 7.3f) }
        line {
            moveTo(15.9f, 15.9f)
            lineTo(21.4f, 21.4f)
        }
    }

    val Create = icon("create") {
        line { roundRect(2.8f, 2.8f, 21.2f, 21.2f, 5f) }
        line {
            moveTo(12f, 7.6f); lineTo(12f, 16.4f)
            moveTo(7.6f, 12f); lineTo(16.4f, 12f)
        }
    }

    /** Short-video tab: clapper board. */
    val Reels = icon("reels") {
        line { roundRect(2.8f, 2.8f, 21.2f, 21.2f, 5f) }
        line {
            moveTo(2.8f, 8.2f); lineTo(21.2f, 8.2f)
            moveTo(8.6f, 2.9f); lineTo(11.4f, 8.1f)
            moveTo(14.4f, 2.9f); lineTo(17.2f, 8.1f)
        }
        solid {
            moveTo(10f, 11.4f)
            lineTo(15.4f, 14.7f)
            lineTo(10f, 18f)
            close()
        }
    }

    /** Direct messages: round bubble with a zig-zag bolt. */
    val Messages = icon("messages") {
        line {
            moveTo(4.7f, 17.3f)
            arcTo(9.3f, 9.3f, 0f, true, true, 7.8f, 20.1f)
            lineTo(2.8f, 21.3f)
            close()
        }
        line {
            moveTo(7.3f, 14.2f)
            lineTo(10.6f, 10.4f)
            lineTo(13.2f, 12.6f)
            lineTo(16.7f, 9.3f)
        }
    }

    val ChevronDown = icon("chevron") {
        line {
            moveTo(6.5f, 9.5f)
            lineTo(12f, 15f)
            lineTo(17.5f, 9.5f)
        }
    }

    val MoreVertical = icon("more") {
        solid {
            circle(12f, 5f, 1.6f)
            circle(12f, 12f, 1.6f)
            circle(12f, 19f, 1.6f)
        }
    }

    val Plus = icon("plus") {
        path(stroke = SolidColor(Color.Black), strokeLineWidth = 2.6f, strokeLineCap = StrokeCap.Round) {
            moveTo(12f, 6.5f); lineTo(12f, 17.5f)
            moveTo(6.5f, 12f); lineTo(17.5f, 12f)
        }
    }
}

/** Blue scalloped verification badge with a white tick (two colours, so not an Icon). */
@Composable
fun VerifiedBadge(size: Dp = 12.dp, color: Color = FeedColors.Blue) {
    Canvas(Modifier.size(size)) {
        val c = Offset(this.size.width / 2, this.size.height / 2)
        val outer = this.size.minDimension / 2
        val inner = outer * 0.84f
        val n = 16
        val star = Path().apply {
            for (i in 0 until n * 2) {
                val r = if (i % 2 == 0) outer else inner
                val a = PI * i / n - PI / 2
                val x = c.x + r * cos(a).toFloat()
                val y = c.y + r * sin(a).toFloat()
                if (i == 0) moveTo(x, y) else lineTo(x, y)
            }
            close()
        }
        drawPath(star, color)
        val w = this.size.width
        val tick = Path().apply {
            moveTo(w * 0.30f, w * 0.52f)
            lineTo(w * 0.45f, w * 0.66f)
            lineTo(w * 0.71f, w * 0.38f)
        }
        drawPath(tick, Color.White, style = Stroke(width = w * 0.11f, cap = StrokeCap.Round, join = StrokeJoin.Round))
    }
}

/** Colours of the photo-feed look, for light and dark themes. */
object FeedColors {
    val Blue = Color(0xFF0095F6)
    val LikeRed = Color(0xFFFF3040)
    val StoryRing = listOf(Color(0xFFFEDA75), Color(0xFFFA7E1E), Color(0xFFD62976), Color(0xFF962FBF), Color(0xFF4F5BD5))
    fun secondary(dark: Boolean) = if (dark) Color(0xFFA8A8A8) else Color(0xFF737373)
    fun divider(dark: Boolean) = if (dark) Color(0xFF262626) else Color(0xFFDBDBDB)
}
