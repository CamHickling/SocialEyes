package org.socialeyes.pictogram.device

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import org.socialeyes.pictogram.study.Display
import org.socialeyes.pictogram.study.Markers
import org.socialeyes.pictogram.study.Neon
import org.socialeyes.pictogram.study.OnScreenTagsConfig
import org.socialeyes.pictogram.study.SceneExposure
import org.socialeyes.pictogram.study.StudyConfig
import org.socialeyes.pictogram.study.StudyJson

class PhoneSettingsTest {

    // as the loader writes it (python phone/models.py)
    private val edge = StudyJson.decodeFromString<PhoneSettings>(
        """{"manufacturer": "motorola", "model": "motorola edge 40 pro", "brightness": 0.3,
            "scene_exposure": {"mode": "auto", "brightness": -32}, "source": "settings test T01"}""",
    )

    private fun study(tags: Boolean = true, brightness: Double? = null, exposure: SceneExposure? = null, autoRecord: Boolean = true) =
        StudyConfig(
            id = "s", version = 1, procedure = emptyList(),
            display = Display(brightness = brightness),
            markers = Markers(onScreen = OnScreenTagsConfig(steps = if (tags) listOf("feed") else emptyList(), layout = "bars")),
            neon = Neon(autoRecord = autoRecord, sceneExposure = exposure),
        )

    @Test
    fun blanksAreFilledFromThePhoneModel() {
        val (s, filled) = PhoneSettings.fill(study(), edge)
        assertEquals(0.3, s.display.brightness!!, 1e-9)
        assertEquals(SceneExposure(mode = "auto", brightness = -32), s.neon.sceneExposure)
        assertEquals(listOf("display.brightness", "neon.scene_exposure"), filled)
    }

    @Test
    fun theStudysOwnSettingsWin() {
        val own = SceneExposure(mode = "manual", exposureUs = 1000)
        val (s, filled) = PhoneSettings.fill(study(brightness = 0.6, exposure = own), edge)
        assertEquals(0.6, s.display.brightness!!, 1e-9)
        assertEquals(own, s.neon.sceneExposure)
        assertTrue(filled.isEmpty())
    }

    @Test
    fun onlyEyeTrackingStudiesAndExposureOnlyWhenTheAppRecords() {
        val plain = study(tags = false)
        val (s, filled) = PhoneSettings.fill(plain, edge)
        assertSame(plain, s)
        assertTrue(filled.isEmpty())
        assertEquals(listOf("display.brightness"), PhoneSettings.fill(study(autoRecord = false), edge).second)
        assertTrue(PhoneSettings.fill(study(), null).second.isEmpty())
    }

    @Test
    fun matchesThePhoneModelIgnoringCase() {
        assertTrue(edge.matches("Motorola", "Motorola Edge 40 Pro"))
        assertFalse(edge.matches("Google", "Pixel 3"))
    }
}
