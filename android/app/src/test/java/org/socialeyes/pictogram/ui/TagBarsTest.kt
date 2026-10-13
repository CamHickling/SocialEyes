package org.socialeyes.pictogram.ui

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Test
import org.socialeyes.pictogram.study.Step

class TagBarsTest {
    @Test
    fun everyVariantShowsOncePerRoundAndTheOrderAlternates() {
        assertEquals(listOf(0, 1, 2, 2, 1, 0), barOrder(3, 2, hold = 0))
        assertEquals(listOf(2, 1, 0, 0, 1, 2), barOrder(3, 2, hold = 1))
    }

    @Test
    fun variantsAreReadFromTheCompiledStep() {
        val step = Step(Json.parseToJsonElement(
            """{"id": "bars", "type": "tag_bars", "variants": [
                 {"family": "tag16h5", "size_mm": 10.0, "grey": 0.0, "tag_ids": [0, 1, 2, 3]},
                 {"family": "tag36h11", "size_mm": 12.0, "grey": 0.4, "tag_ids": [60, 61, 62, 63]},
                 {"family": "tag16h5", "size_mm": 8.0, "tag_ids": [4, 5]}]}"""
        ) as JsonObject)
        val v = barVariants(step)
        assertEquals(2, v.size) // the last has too few ids
        assertEquals("16h5 10 mm", v[0].label)
        assertEquals(6, v[0].cells)
        assertEquals("36h11 12 mm grey 40%", v[1].label)
        assertEquals(listOf(60, 61, 62, 63), v[1].ids)
    }
}
