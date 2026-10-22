package org.socialeyes.pictogram.neon

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.DataInputStream
import java.net.ServerSocket
import java.nio.ByteBuffer
import kotlin.random.Random

class ValidationCheckTest {
    // 9 dots on a 1080 x 2400 screen; the phone at ~35 cm: about 0.35 scene px per screen px
    private val screen = listOf(0.1, 0.5, 0.9).flatMap { fy -> listOf(0.1, 0.5, 0.9).map { fx -> fx * 1080 to fy * 2400 } }

    private fun dots(look: (Int, Double, Double) -> Pair<Double, Double>, worn: Boolean = true, perDot: Int = 100,
                     seed: Int = 1): List<DotGaze> {
        val rnd = Random(seed)
        return screen.mapIndexed { k, (sx, sy) ->
            val (gx, gy) = look(k, sx, sy)
            DotGaze(sx, sy, List(perDot) {
                GazeSample(it.toLong(), (gx + rnd.nextDouble(-6.0, 6.0)).toFloat(), (gy + rnd.nextDouble(-6.0, 6.0)).toFloat(), worn)
            }, windowS = 0.5)
        }
    }

    private val good: (Int, Double, Double) -> Pair<Double, Double> = { _, sx, sy -> 500 + 0.35 * sx + 0.05 * sy to 300 + 0.35 * sy }

    @Test
    fun goodValidationPasses() {
        val r = ValidationCheck.evaluate(dots(good), sceneStreaming = true)
        assertTrue(r.reasons.toString(), r.passed)
        assertEquals(9, r.followed)
        assertEquals(200.0, r.rateHz, 0.1)
    }

    @Test
    fun twoMissedDotsAreFoundButStillPass() {
        val r = ValidationCheck.evaluate(dots({ k, sx, sy -> if (k == 2 || k == 6) 800.0 to 900.0 else good(k, sx, sy) }))
        assertEquals(listOf(true, true, false, true, true, true, false, true, true), r.perDot)
        assertTrue(r.passed)   // 7 of 9 >= 75%
    }

    @Test
    fun frozenGazeFails() {
        val r = ValidationCheck.evaluate(dots({ _, _, _ -> 800.0 to 600.0 }))
        assertFalse(r.passed)
        assertEquals(0, r.followed)
        assertTrue(r.reasons.any { "followed 0 of 9" in it })
    }

    @Test
    fun randomGazeFails() {
        val rnd = Random(7)
        val r = ValidationCheck.evaluate(dots({ _, _, _ -> rnd.nextDouble(0.0, 1600.0) to rnd.nextDouble(0.0, 1200.0) }))
        assertFalse(r.passed)
    }

    @Test
    fun slowOrUnwornGazeFails() {
        val slow = ValidationCheck.evaluate(dots(good, perDot = 30))   // 60 Hz
        assertFalse(slow.passed)
        assertTrue(slow.reasons.any { "samples a second" in it })
        val off = ValidationCheck.evaluate(dots(good, worn = false))
        assertTrue(off.reasons.any { "not being worn" in it })
        assertFalse(ValidationCheck.evaluate(dots(good), sceneStreaming = false).passed)
    }

    // ------------------------------------------------------------ the stream

    private fun rtp(x: Float, y: Float, worn: Boolean, extra: Int = 0): ByteArray =
        ByteBuffer.allocate(12 + 9 + extra).put(0x80.toByte()).put(96).putShort(1).putInt(0).putInt(0)
            .putFloat(x).putFloat(y).put(if (worn) 1 else 0).array()

    @Test
    fun gazePayloadIsParsed() {
        assertEquals(Triple(812.5f, 400.25f, true), GazeStream.parseGaze(rtp(812.5f, 400.25f, true)))
        assertEquals(Triple(1f, 2f, false), GazeStream.parseGaze(rtp(1f, 2f, false, extra = 68)))   // per-eye data after it
        assertEquals(null, GazeStream.parseGaze(ByteArray(15)))
    }

    @Test
    fun interleavedPacketsSkipOtherBytes() {
        val p = rtp(3f, 4f, true)
        val bytes = "junk".toByteArray() + byteArrayOf('$'.code.toByte(), 0, (p.size shr 8).toByte(), p.size.toByte()) + p
        val (channel, data) = GazeStream.readInterleaved(DataInputStream(ByteArrayInputStream(bytes)))!!
        assertEquals(0, channel)
        assertEquals(Triple(3f, 4f, true), GazeStream.parseGaze(data))
    }

    @Test
    fun trackUrlFollowsTheSdp() {
        val url = "rtsp://127.0.0.1:8086/?camera=gaze"
        assertEquals("rtsp://h/track1", GazeStream.trackUrl(url, "v=0\r\na=control:*\r\nm=application 0 RTP/AVP 96\r\na=control:rtsp://h/track1\r\n"))
        assertEquals("$url/trackID=0", GazeStream.trackUrl(url, "v=0\r\nm=application 0 RTP/AVP 96\r\na=control:trackID=0\r\n"))
        assertEquals(url, GazeStream.trackUrl(url, "v=0\r\n"))
    }

    @Test
    fun streamTalksRtspAndKeepsSamples() {
        ServerSocket(0).use { server ->
            val companion = Thread {
                server.accept().use { c ->
                    val input = c.getInputStream().bufferedReader()
                    val out = c.getOutputStream()
                    fun reply(extra: String = "", body: String = "") {
                        // read one request (up to the blank line)
                        while (input.readLine().orEmpty().isNotEmpty()) Unit
                        out.write("RTSP/1.0 200 OK\r\nCSeq: 1\r\n${extra}Content-Length: ${body.length}\r\n\r\n$body".toByteArray())
                    }
                    reply(body = "v=0\r\nm=application 0 RTP/AVP 96\r\na=control:trackID=0\r\n")
                    reply("Session: 12345;timeout=60\r\nTransport: RTP/AVP/TCP;interleaved=0-1\r\n")
                    reply()
                    repeat(5) { k ->
                        val p = rtp(100f + k, 200f, true)
                        out.write(byteArrayOf('$'.code.toByte(), 0, 0, p.size.toByte()) + p)
                    }
                    out.flush()
                    Thread.sleep(300)
                }
            }.apply { start() }
            var clock = 0L
            val stream = GazeStream(port = server.localPort, clockNs = { ++clock })
            stream.start()
            companion.join(5000)
            Thread.sleep(200)
            stream.stop()
            val got = stream.between(0, Long.MAX_VALUE)
            assertEquals(stream.error, 5, got.size)
            assertEquals(listOf(100f, 101f, 102f, 103f, 104f), got.map { it.x })
        }
    }
}
