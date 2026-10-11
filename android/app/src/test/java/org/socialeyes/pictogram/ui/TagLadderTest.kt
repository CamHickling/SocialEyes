package org.socialeyes.pictogram.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs

class TagLadderTest {
    // Motorola Edge 40 Pro: 1080 x 2400 px at ~397 dpi
    private val w = 1080 / 397.6 * 25.4
    private val h = 2400 / 395.8 * 25.4
    private fun layout(phase: Int) =
        ladderLayout(w, h, listOf(8.0, 10.0, 12.0, 14.0), listOf(3.0, 4.0, 5.0, 6.0), listOf(1.5, 3.5), 12.0, 20, phase)

    @Test
    fun sixteenUniqueTagsOnScreen() {
        for (phase in 0..1) {
            val tags = layout(phase)
            assertEquals((20..35).toList(), tags.map { it.id }.sorted())
            tags.forEach { t ->
                val half = t.sizeMm / 2
                assertTrue("tag ${t.id} off screen", t.cxMm - half >= 0 && t.cxMm + half <= w && t.cyMm - half >= 0 && t.cyMm + half <= h)
            }
        }
    }

    @Test
    fun blackSquaresAndQuietZonesDontOverlap() {
        for (phase in 0..1) {
            val tags = layout(phase)
            for (a in tags) for (b in tags) {
                if (a.id >= b.id) continue
                // black square plus a 1-cell quiet zone each
                val ra = a.sizeMm * 10 / 16
                val rb = b.sizeMm * 10 / 16
                val apart = abs(a.cxMm - b.cxMm) >= ra + rb || abs(a.cyMm - b.cyMm) >= ra + rb
                assertTrue("tags ${a.id} and ${b.id} overlap", apart)
            }
        }
    }

    @Test
    fun edgeDistancesMatchWhatIsTested() {
        val tags = layout(0)
        tags.filter { it.kind == "left_inset" }.forEach { assertEquals(it.valueMm, it.cxMm - it.sizeMm / 2, 1e-9) }
        tags.filter { it.kind == "right_inset" }.forEach { assertEquals(it.valueMm, w - it.cxMm - it.sizeMm / 2, 1e-9) }
        tags.filter { it.kind == "top_gap" }.forEach { assertEquals(it.valueMm, it.cyMm - it.sizeMm / 2, 1e-9) }
        tags.filter { it.kind == "bottom_gap" }.forEach { assertEquals(it.valueMm, h - it.cyMm - it.sizeMm / 2, 1e-9) }
    }

    @Test
    fun oddPhasesReverseTheOrder() {
        val sizesTopDown = { p: Int -> layout(p).filter { it.kind == "size" }.sortedBy { it.cyMm }.map { it.valueMm } }
        assertEquals(listOf(8.0, 10.0, 12.0, 14.0), sizesTopDown(0))
        assertEquals(listOf(14.0, 12.0, 10.0, 8.0), sizesTopDown(1))
    }
}
