package org.socialeyes.pictogram.neon

import java.io.BufferedInputStream
import java.io.DataInputStream
import java.io.IOException
import java.io.InputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.nio.ByteBuffer
import java.util.ArrayDeque

/** One gaze sample from Neon Companion: scene camera pixels, whether the glasses are worn, and when
 *  it arrived (the clock given to [GazeStream], the session's elapsed-realtime ns in the app). */
data class GazeSample(val tNs: Long, val x: Float, val y: Float, val worn: Boolean)

/**
 * Companion's live gaze over its real-time API: RTSP on this phone (127.0.0.1:8086, `?camera=gaze`),
 * RTP interleaved on the same TCP connection. Each RTP payload starts with x, y (float32, big-endian,
 * scene camera pixels) and a worn byte, as in Pupil Labs' real-time API client; newer Companions send
 * more after them (per-eye data), which is ignored. Keeps the last [keepMs] of samples for the live
 * validation check (ValidationCheck). Runs on its own thread; [stop] ends it.
 */
class GazeStream(
    private val host: String = "127.0.0.1",
    private val port: Int = 8086,
    private val keepMs: Long = 120_000,
    private val clockNs: () -> Long,
) {
    private val samples = ArrayDeque<GazeSample>()
    @Volatile private var socket: Socket? = null
    @Volatile var error: String? = null
        private set
    @Volatile var received = 0L
        private set
    private var thread: Thread? = null

    fun start() {
        thread = Thread({ run() }, "neon-gaze").apply { isDaemon = true; start() }
    }

    fun stop() {
        runCatching { socket?.close() }
        thread = null
    }

    /** Samples that arrived between the two times (inclusive). */
    fun between(fromNs: Long, toNs: Long): List<GazeSample> = synchronized(samples) {
        samples.filter { it.tNs in fromNs..toNs }
    }

    private fun run() {
        try {
            val s = Socket()
            socket = s
            s.connect(InetSocketAddress(host, port), 3000)
            s.soTimeout = 5000
            val input = DataInputStream(BufferedInputStream(s.getInputStream()))
            val out = s.getOutputStream()
            val url = "rtsp://$host:$port/?camera=gaze"
            var cseq = 1
            fun request(method: String, target: String, extra: String = ""): Pair<Map<String, String>, String> {
                out.write("$method $target RTSP/1.0\r\nCSeq: ${cseq++}\r\n$extra\r\n".toByteArray(Charsets.US_ASCII))
                out.flush()
                return readResponse(input)
            }
            val (_, sdp) = request("DESCRIBE", url, "Accept: application/sdp\r\n")
            val track = trackUrl(url, sdp)
            val (setup, _) = request("SETUP", track, "Transport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n")
            val session = setup["session"]?.substringBefore(';')?.trim()
                ?: throw IOException("Companion's gaze stream gave no RTSP session")
            request("PLAY", url, "Session: $session\r\nRange: npt=0.000-\r\n")
            s.soTimeout = 0
            while (!s.isClosed) {
                val (channel, packet) = readInterleaved(input) ?: break
                if (channel != 0) continue   // RTCP
                val g = parseGaze(packet) ?: continue
                add(GazeSample(clockNs(), g.first, g.second, g.third))
            }
        } catch (e: Exception) {
            if (socket?.isClosed != true) error = e.message ?: e.toString()
        } finally {
            runCatching { socket?.close() }
        }
    }

    private fun add(g: GazeSample) = synchronized(samples) {
        samples.addLast(g)
        received++
        val cutoff = g.tNs - keepMs * 1_000_000
        while (samples.isNotEmpty() && samples.first().tNs < cutoff) samples.removeFirst()
    }

    companion object {
        /** An RTSP response: headers (lower-case names) and body. */
        fun readResponse(input: DataInputStream): Pair<Map<String, String>, String> {
            val status = readLine(input)
            if (!status.startsWith("RTSP/1.0 200")) throw IOException("Companion's gaze stream answered: $status")
            val headers = mutableMapOf<String, String>()
            while (true) {
                val line = readLine(input)
                if (line.isEmpty()) break
                val i = line.indexOf(':')
                if (i > 0) headers[line.substring(0, i).trim().lowercase()] = line.substring(i + 1).trim()
            }
            val n = headers["content-length"]?.toIntOrNull() ?: 0
            val body = ByteArray(n).also { input.readFully(it) }
            return headers to String(body, Charsets.UTF_8)
        }

        private fun readLine(input: InputStream): String {
            val sb = StringBuilder()
            while (true) {
                val c = input.read()
                if (c < 0) throw IOException("Companion closed the gaze stream")
                if (c == '\n'.code) return sb.toString().trimEnd('\r')
                sb.append(c.toChar())
            }
        }

        /** The SETUP url: the SDP's media-level a=control (absolute, or relative to the stream url). */
        fun trackUrl(url: String, sdp: String): String {
            val media = sdp.substringAfter("m=", "")
            val control = Regex("""a=control:(\S+)""").find(media)?.groupValues?.get(1) ?: return url
            return when {
                control.startsWith("rtsp://") -> control
                control == "*" -> url
                else -> url.trimEnd('/') + "/" + control
            }
        }

        /** The next interleaved packet ('$', channel, 16-bit length, data), or null at the end. */
        fun readInterleaved(input: DataInputStream): Pair<Int, ByteArray>? {
            while (true) {
                val b = input.read()
                if (b < 0) return null
                if (b != '$'.code) continue   // skip anything else (e.g. an RTSP reply)
                val channel = input.readUnsignedByte()
                val len = input.readUnsignedShort()
                val data = ByteArray(len).also { input.readFully(it) }
                return channel to data
            }
        }

        /** x, y and worn from an RTP packet's payload, or null if it is too short. */
        fun parseGaze(packet: ByteArray): Triple<Float, Float, Boolean>? {
            if (packet.size < 12) return null
            val cc = packet[0].toInt() and 0x0F
            val ext = (packet[0].toInt() and 0x10) != 0
            var off = 12 + 4 * cc
            if (ext) {
                if (packet.size < off + 4) return null
                val words = ((packet[off + 2].toInt() and 0xFF) shl 8) or (packet[off + 3].toInt() and 0xFF)
                off += 4 + 4 * words
            }
            if (packet.size < off + 9) return null
            val buf = ByteBuffer.wrap(packet, off, 9)   // big-endian
            return Triple(buf.float, buf.float, buf.get().toInt() != 0)
        }
    }
}
