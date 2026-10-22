package org.socialeyes.pictogram.ui

import org.junit.Assert.assertEquals
import org.junit.Test
import org.socialeyes.pictogram.neon.CameraControl

class SettingsTestTest {
    private val ae = CameraControl("brightness", current = "0", min = -64, max = 64)

    @Test
    fun manualSetsTheExposureTime() {
        assertEquals(mapOf("ae_mode" to "manual", "man_exp" to "1000"), TestExposure("manual", 1000).values(ae))
    }

    @Test
    fun autoPutsTheBrightnessBackOrShiftsIt() {
        assertEquals("0", TestExposure("auto").values(ae)["brightness"])
        assertEquals("-32", TestExposure("auto", autoBias = -0.5).values(ae)["brightness"])
        assertEquals("64", TestExposure("auto", autoBias = 1.0).values(ae)["brightness"])
        assertEquals(mapOf("ae_mode" to "auto"), TestExposure("auto", autoBias = -0.5).values(null))
    }

    @Test
    fun labelsNameEachSetting() {
        assertEquals("brightness 0.30, auto -50%", TestSetting(0.3, TestExposure("auto", autoBias = -0.5)).label)
        assertEquals("brightness 0.45, 2000 us", TestSetting(0.45, TestExposure("manual", 2000)).label)
    }
}
