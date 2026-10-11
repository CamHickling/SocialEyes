package org.socialeyes.pictogram.neon

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.socialeyes.pictogram.study.SceneExposure
import java.nio.ByteBuffer
import java.nio.ByteOrder

class NeonSetupTest {

    @Test
    fun statusReadsPhoneHardwareAndStreams() {
        // shape of /api/status (Pupil Labs real-time API): one Sensor entry per stream and connection type
        val results = Json.parseToJsonElement(
            """{"result": [
              {"model": "Phone", "data": {"battery_level": 23, "battery_state": "LOW", "device_id": "x", "device_name": "Phone 2",
                                          "ip": "10.0.0.2", "memory": 1000, "memory_state": "OK"}},
              {"model": "Hardware", "data": {"version": "2.0", "module_serial": "495855", "frame_name": "Just act natural"}},
              {"model": "Sensor", "data": {"sensor": "gaze", "conn_type": "WEBSOCKET", "connected": false}},
              {"model": "Sensor", "data": {"sensor": "gaze", "conn_type": "DIRECT", "connected": true}},
              {"model": "Sensor", "data": {"sensor": "world", "conn_type": "DIRECT", "connected": false}},
              {"model": "Recording", "data": {"action": "STOP", "id": "r", "message": "", "rec_duration_ns": 0}}
            ]}""",
        ).jsonObject["result"]!!.jsonArray
        val s = NeonStatus.parse(results)
        assertEquals("495855", s.moduleSerial)
        assertTrue(s.glassesConnected)
        assertFalse(s.recording)
        assertEquals(23, s.batteryLevel)
        assertEquals("LOW", s.batteryState)
        assertEquals(mapOf("gaze" to true, "world" to false), s.streams)
    }

    @Test
    fun noGlassesMeansNoModuleSerial() {
        val results = Json.parseToJsonElement("""[{"model": "Hardware", "data": {"module_serial": "-1"}}]""").jsonArray
        assertFalse(NeonStatus.parse(results).glassesConnected)
    }

    private val camera = mapOf(
        "ae_mode" to CameraControl("ae_mode", "auto", allowed = listOf("auto", "manual")),
        "man_exp" to CameraControl("man_exp", "8000", min = 1, max = 30000),
        "gain" to CameraControl("gain", "1", min = 1, max = 16),
        "brightness" to CameraControl("brightness", "0", min = -64, max = 64),
    )

    @Test
    fun exposureChangesOnlyWhatDiffersAndCanBePutBack() {
        val wanted = NeonSetup.exposureValues(SceneExposure("manual", exposureUs = 2000, gain = 1))
        val (change, problems) = NeonSetup.exposureChange(wanted, camera)
        assertTrue(problems.isEmpty())
        assertEquals(mapOf("ae_mode" to "manual", "man_exp" to "2000"), change)
        assertEquals(mapOf("ae_mode" to "auto", "man_exp" to "8000"), NeonSetup.restoreValues(change, camera))
    }

    @Test
    fun exposureOutsideCompanionsRangeIsAProblem() {
        val (_, problems) = NeonSetup.exposureChange(mapOf("ae_mode" to "manual", "man_exp" to "50000"), camera)
        assertEquals(1, problems.size)
        assertTrue(problems[0], problems[0].contains("man_exp"))
        assertNull(camera.getValue("ae_mode").reject("manual"))
        assertTrue(camera.getValue("ae_mode").reject("highlights") != null)
    }

    @Test
    fun templateFieldsMatchByTitleIgnoringCase() {
        val items = listOf(TemplateItem("id-1", "Participant ", true, "TEXT"), TemplateItem("id-2", "Notes", false, "PARAGRAPH"))
        val (answers, filled, missing) = NeonSetup.templateAnswers(
            items, mapOf("participant" to "{participant_id}", "Study" to "{study_id} v{study_version}"),
            mapOf("participant_id" to "P001", "study_id" to "bodyimage", "study_version" to "3"),
        )
        assertEquals(mapOf("id-1" to listOf("P001")), answers)
        assertEquals(listOf("Participant "), filled)
        assertEquals(listOf("Study"), missing)
        assertEquals("bodyimage v3 {unknown}", NeonSetup.fill("{study_id} v{study_version} {unknown}",
            mapOf("study_id" to "bodyimage", "study_version" to "3")))
    }

    @Test
    fun calibrationFileLayout() {
        val buf = ByteBuffer.allocate(7 + 17 * 8 + 100).order(ByteOrder.LITTLE_ENDIAN)
        buf.put(1)
        buf.put("495855".toByteArray())
        doubleArrayOf(885.5, 0.0, 812.0, 0.0, 884.9, 605.0, 0.0, 0.0, 1.0).forEach { buf.putDouble(it) }
        DoubleArray(8) { -0.1 * it }.forEach { buf.putDouble(it) }
        val c = SceneCalibration.parse(buf.array())
        assertEquals("495855", c.serial)
        assertEquals(885.5, c.fx, 1e-9)
        assertEquals(884.9, c.fy, 1e-9)
        assertEquals(812.0, c.cx, 1e-9)
        assertEquals(605.0, c.cy, 1e-9)
        assertEquals(-0.7, c.distortion[7], 1e-9)
    }
}
