package org.socialeyes.pictogram.log

import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.positionInWindow

/**
 * Collects where each post and its parts are, and writes viewport.csv rows for
 * every drawn frame in which any of them moved (docs/EVENT_LOG.md, "viewport.csv").
 *
 * Rectangles come from Compose layout (window coordinates, unclipped) and are
 * shifted to screen coordinates when written. Use from the main thread only.
 *
 * Timing: rows get the vsync time of the frame whose layout produced them. The
 * frame reaches the display a frame or two later; that constant lag is the same
 * for the sync patch, so it drops out when the eye tracker is synchronised.
 */
class ViewportTracker(private val log: SessionLog) {
    private val posts = LinkedHashMap<String, LinkedHashMap<String, ScreenRect>>()
    private var dirty = true
    private var frame = 0L

    /** Elapsed-clock vsync time of the frame being drawn; set every frame. */
    var vsyncNs = 0L

    /** The feed's scrolling area, window coordinates. Posts outside it are not written. */
    var feedArea: ScreenRect? = null

    var scrollY: () -> Float = { 0f }

    // The comments sheet, drawn over the feed: element -> rectangle (window coordinates).
    private val overlay = LinkedHashMap<String, ScreenRect>()
    private var overlayPost: String? = null
    private var overlayClip: ScreenRect? = null

    /** Window size, for deciding whether sheet elements are on screen. */
    var windowSize: Pair<Float, Float> = Float.MAX_VALUE to Float.MAX_VALUE

    /** An element drawn over the feed: the comments sheet's `sheet`, `sheet_input` and
     *  `sheet_comment_<n>`, or an open `story` (with the story_id as [postId]). */
    fun updateOverlay(postId: String, element: String, coords: LayoutCoordinates) {
        if (!coords.isAttached) return
        val p = coords.positionInWindow()
        val r = ScreenRect(p.x, p.y, p.x + coords.size.width, p.y + coords.size.height)
        if (overlayPost != postId) { overlay.clear(); overlayPost = postId }
        if (overlay[element] != r) {
            overlay[element] = r
            dirty = true
        }
    }

    /** The part of the sheet comments are visible in (below its header). */
    fun setOverlayClip(coords: LayoutCoordinates) {
        if (!coords.isAttached) return
        val p = coords.positionInWindow()
        val r = ScreenRect(p.x, p.y, p.x + coords.size.width, p.y + coords.size.height)
        if (overlayClip != r) { overlayClip = r; dirty = true }
    }

    fun clearOverlay() {
        if (overlayPost == null) return
        overlay.clear()
        overlayPost = null
        overlayClip = null
        dirty = true
    }

    fun update(postId: String, element: String, coords: LayoutCoordinates) {
        if (!coords.isAttached) return
        val p = coords.positionInWindow()
        val r = ScreenRect(p.x, p.y, p.x + coords.size.width, p.y + coords.size.height)
        val parts = posts.getOrPut(postId) { LinkedHashMap() }
        if (parts[element] != r) {
            parts[element] = r
            dirty = true
        }
    }

    /** The post left composition (scrolled far out of view). */
    fun remove(postId: String) {
        if (posts.remove(postId) != null) dirty = true
    }

    /** Call before each draw with the window's position on screen. */
    fun onDraw(windowX: Float, windowY: Float) {
        if (!dirty) return
        dirty = false
        val t = if (vsyncNs > 0) vsyncNs else Clocks.elapsedNs()
        log.viewportFrame(t, frame, scrollY())
        val area = feedArea?.offset(windowX, windowY)
        for ((postId, parts) in posts) {
            val card = parts["post"]?.offset(windowX, windowY) ?: continue
            if (area != null && !card.intersects(area)) continue
            log.viewportElement(t, frame, postId, "post", card)
            for ((element, r) in parts) {
                if (element != "post") log.viewportElement(t, frame, postId, element, r.offset(windowX, windowY))
            }
        }
        overlayPost?.let { postId ->
            val window = ScreenRect(0f, 0f, windowSize.first, windowSize.second)
            for ((element, r) in overlay) {
                // only comments are clipped to the sheet's list area
                val inView = r.intersects(window) &&
                    (!element.startsWith("sheet_comment_") || overlayClip?.let(r::intersects) != false)
                if (inView) log.viewportElement(t, frame, postId, element, r.offset(windowX, windowY))
            }
        }
        frame++
    }

    /** The final `frame` row with no elements, written when the feed step ends. */
    fun close() {
        log.viewportFrame(Clocks.elapsedNs(), frame, scrollY())
        posts.clear()
        overlay.clear()
        overlayPost = null
    }
}
