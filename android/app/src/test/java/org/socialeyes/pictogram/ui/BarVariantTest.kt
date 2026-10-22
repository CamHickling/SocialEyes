package org.socialeyes.pictogram.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class BarVariantTest {
    // the same labels as the study's TagBarsVariant.label (Python), which the analysis matches on
    @Test
    fun labelsMatchTheStudys() {
        assertEquals("16h5 10 mm", BarVariant("tag16h5", 10.0, 0.0, listOf(0, 1, 2, 3)).label)
        assertEquals("16h5 10 mm grey 40%", BarVariant("tag16h5", 10.0, 0.4, listOf(0, 1, 2, 3)).label)
        assertEquals("16h5 9 mm, 3 mm in, gap 1.5 mm", BarVariant("tag16h5", 9.0, 0.0, listOf(0, 1, 2, 3), 3.0, 1.5).label)
    }
}
