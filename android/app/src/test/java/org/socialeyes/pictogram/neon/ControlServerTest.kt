package org.socialeyes.pictogram.neon

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.HttpURLConnection
import java.net.ServerSocket
import java.net.URL

class ControlServerTest {

    private fun freePort() = ServerSocket(0).use { it.localPort }

    /** As socialeyes.gaze.display_calibration.AppLink sends it (urllib: JSON body, Content-Length). */
    private fun call(port: Int, path: String, body: String? = null): Pair<Int, String> {
        val conn = URL("http://127.0.0.1:$port$path").openConnection() as HttpURLConnection
        conn.requestMethod = if (body == null) "GET" else "POST"
        conn.setRequestProperty("Content-Type", "application/json")
        if (body != null) {
            conn.doOutput = true
            conn.outputStream.use { it.write(body.toByteArray()) }
        }
        val code = conn.responseCode
        val text = (if (code == 200) conn.inputStream else conn.errorStream).bufferedReader().use { it.readText() }
        return code to text
    }

    @Test
    fun answersJsonRequestsAndReportsErrors() {
        val seen = mutableListOf<ControlRequest>()
        val port = freePort()
        val server = ControlServer(port) { req ->
            seen += req
            when (req.path) {
                "/state" -> buildJsonObject { put("step_id", "dcal") }
                "/apply" -> buildJsonObject {
                    put("applied_unix_ns", 42L)
                    put("brightness", (req.body!!["brightness"] as JsonPrimitive).doubleOrNull!!)
                }
                else -> error("unknown request ${req.method} ${req.path}")
            }
        }
        server.start()
        try {
            val (c1, t1) = call(port, "/state")
            assertEquals(200, c1)
            assertEquals("dcal", Json.parseToJsonElement(t1).jsonObject["step_id"]!!.jsonPrimitive.content)

            val (c2, t2) = call(port, "/apply?x=1", """{"brightness": 0.55, "camera": {"ae_mode": "manual", "man_exp": "2000"}}""")
            assertEquals(200, c2)
            val r = Json.parseToJsonElement(t2).jsonObject
            assertEquals(42L, r["applied_unix_ns"]!!.jsonPrimitive.content.toLong())
            assertEquals(0.55, r["brightness"]!!.jsonPrimitive.doubleOrNull!!, 1e-9)
            assertEquals("POST", seen[1].method)
            assertEquals("/apply", seen[1].path)
            assertEquals("2000", seen[1].body!!["camera"]!!.jsonObject["man_exp"]!!.jsonPrimitive.content)

            val (c3, t3) = call(port, "/nope", "{}")
            assertEquals(500, c3)
            assertTrue(t3, t3.contains("unknown request POST /nope"))
        } finally {
            server.stop()
        }
    }
}
