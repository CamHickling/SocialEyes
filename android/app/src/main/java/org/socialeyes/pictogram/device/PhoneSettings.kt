package org.socialeyes.pictogram.device

import android.os.Build
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import org.socialeyes.pictogram.study.SceneExposure
import org.socialeyes.pictogram.study.StudyConfig
import org.socialeyes.pictogram.study.StudyJson
import org.socialeyes.pictogram.study.StudyPackage
import java.io.File

/**
 * This phone model's tested screen brightness and Neon scene camera exposure (CAM-227), from a
 * settings test run once per model. The computer's loader writes phone_settings.json into the app's
 * files folder (python phone/models.py); an eye-tracking study that leaves display.brightness or
 * neon.scene_exposure blank gets them from here. A study that sets them keeps its own.
 */
@Serializable
data class PhoneSettings(
    val manufacturer: String = "",
    val model: String = "",
    val brightness: Double? = null,
    @SerialName("scene_exposure") val sceneExposure: SceneExposure? = null,
    val source: String = "",
) {
    /** Whether these are for this phone's model (the file stays when a phone's storage is copied). */
    fun matches(manufacturer: String, model: String): Boolean =
        this.manufacturer.trim().equals(manufacturer.trim(), ignoreCase = true) &&
            this.model.trim().equals(model.trim(), ignoreCase = true)

    companion object {
        const val FILE = "phone_settings.json"

        /** The file in [filesDir], if there is one for this phone's model. */
        fun read(filesDir: File?): PhoneSettings? = runCatching {
            StudyJson.decodeFromString<PhoneSettings>(File(filesDir, FILE).readText())
        }.getOrNull()?.takeIf { it.matches(Build.MANUFACTURER, Build.MODEL) }

        /**
         * The study with its blank brightness and exposure filled from [phone], and the fields filled
         * ("display.brightness", "neon.scene_exposure"). Only eye-tracking studies (on-screen tags) are
         * filled, and the exposure only when the app starts the Neon recording.
         */
        fun fill(study: StudyConfig, phone: PhoneSettings?): Pair<StudyConfig, List<String>> {
            if (phone == null || study.markers.onScreen.steps.isEmpty()) return study to emptyList()
            val filled = mutableListOf<String>()
            var display = study.display
            var neon = study.neon
            if (display.brightness == null && phone.brightness != null) {
                display = display.copy(brightness = phone.brightness)
                filled += "display.brightness"
            }
            if (neon.autoRecord && neon.sceneExposure == null && phone.sceneExposure != null) {
                neon = neon.copy(sceneExposure = phone.sceneExposure)
                filled += "neon.scene_exposure"
            }
            return study.copy(display = display, neon = neon) to filled
        }

        /** [pkg] with this phone model's settings filled in where the study leaves them blank. */
        fun apply(pkg: StudyPackage, filesDir: File?): StudyPackage {
            val phone = read(filesDir)
            val (study, filled) = fill(pkg.study, phone)
            if (filled.isEmpty()) return pkg
            return StudyPackage(pkg.dir, pkg.manifest.copy(study = study), phoneSettings = phone, phoneFilled = filled)
        }
    }
}
