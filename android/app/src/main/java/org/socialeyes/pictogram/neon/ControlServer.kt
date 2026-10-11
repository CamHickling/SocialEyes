package org.socialeyes.pictogram.neon

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import java.io.BufferedInputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import kotlin.concurrent.thread

/** One HTTP request: method, path (without the query) and JSON body (null if none). */
data class ControlRequest(val method: String, val path: String, val body: JsonObject?)

/**
 * A tiny HTTP server on the phone's network for a laptop to drive a step (display_calibration):
 * JSON in, JSON out, one request per connection. Runs only while the step is on screen.
 * `handle` runs on the server's thread; an exception becomes a 500 with its message.
 */
class ControlServer(private val port: Int, private val handle: (ControlRequest) -> JsonObject) {
    private var socket: ServerSocket? = null

    fun start() {
        val server = ServerSocket(port)
        socket = server
        thread(name = "control-server", isDaemon = true) {
            while (!server.isClosed) {
                val client = try {
                    server.accept()
                } catch (e: SocketException) {
                    break // closed
                }
                thread(name = "control-request", isDaemon = true) { serve(client) }
            }
        }
    }

    fun stop() {
        runCatching { socket?.close() }
        socket = null
    }

    private fun serve(client: Socket) {
        client.use { s ->
            s.soTimeout = 10_000
            val (code, body) = try {
                val req = readRequest(BufferedInputStream(s.getInputStream()))
                200 to handle(req)
            } catch (e: Exception) {
                500 to buildJsonObject { put("message", e.message ?: e.toString()) }
            }
            writeResponse(s.getOutputStream(), code, body)
        }
    }

    companion object {
        private const val MAX_BODY = 1 shl 20

        fun readRequest(input: InputStream): ControlRequest {
            val line = readLine(input) ?: throw IOException("empty request")
            val parts = line.split(" ")
            if (parts.size < 2) throw IOException("bad request line: $line")
            var length = 0
            while (true) {
                val h = readLine(input) ?: break
                if (h.isEmpty()) break
                val i = h.indexOf(':')
                if (i > 0 && h.substring(0, i).trim().equals("Content-Length", ignoreCase = true)) {
                    length = h.substring(i + 1).trim().toInt()
                }
            }
            if (length > MAX_BODY) throw IOException("request too large")
            val bytes = ByteArray(length)
            var read = 0
            while (read < length) {
                val n = input.read(bytes, read, length - read)
                if (n < 0) throw IOException("request body cut short")
                read += n
            }
            val body = if (length > 0) Json.parseToJsonElement(String(bytes, Charsets.UTF_8)).jsonObject else null
            return ControlRequest(parts[0].uppercase(), parts[1].substringBefore('?'), body)
        }

        private fun readLine(input: InputStream): String? {
            val sb = StringBuilder()
            while (true) {
                val c = input.read()
                if (c < 0) return if (sb.isEmpty()) null else sb.toString()
                if (c == '\n'.code) return sb.toString().trimEnd('\r')
                sb.append(c.toChar())
            }
        }

        fun writeResponse(out: OutputStream, code: Int, body: JsonObject) {
            val bytes = body.toString().toByteArray(Charsets.UTF_8)
            val status = if (code == 200) "OK" else "Error"
            out.write("HTTP/1.1 $code $status\r\nContent-Type: application/json\r\nContent-Length: ${bytes.size}\r\nConnection: close\r\n\r\n".toByteArray())
            out.write(bytes)
            out.flush()
        }

        /** The phone's IPv4 addresses on Wi-Fi or a hotspot (what the laptop connects to). */
        fun localAddresses(): List<String> = runCatching {
            NetworkInterface.getNetworkInterfaces().toList()
                .filter { it.isUp && !it.isLoopback }
                .flatMap { it.inetAddresses.toList() }
                .filterIsInstance<Inet4Address>()
                .map { it.hostAddress.orEmpty() }
                .filter { it.isNotEmpty() }
        }.getOrDefault(emptyList())
    }
}
