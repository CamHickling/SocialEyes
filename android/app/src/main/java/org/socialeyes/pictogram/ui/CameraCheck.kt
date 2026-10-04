package org.socialeyes.pictogram.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Button
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import org.socialeyes.pictogram.Session
import org.socialeyes.pictogram.log.Clocks
import org.socialeyes.pictogram.log.FaceCheckCamera
import org.socialeyes.pictogram.study.Step

/**
 * camera_check step, run by the researcher before the recorded steps: a framing
 * guide and a face-detected indicator. The video itself is never shown (seeing
 * yourself before a body-image task is a manipulation in its own right).
 * Continue unlocks once a face has been in view for `min_face_s` seconds;
 * after 15 s "Continue without face" allows going on anyway.
 * Logs `camera_check` with result `ok` or `failed` and `face_s`.
 */
@Composable
fun CameraCheckStep(session: Session, step: Step, onContinue: () -> Unit) {
    val context = LocalContext.current
    val minFaceS = step.double("min_face_s") ?: 3.0
    val instructions = step.str("instructions") ?: "Hold the phone as you normally would and look at the screen."
    val startNs = remember { Clocks.elapsedNs() }
    var face by remember { mutableStateOf(false) }
    var unavailable by remember { mutableStateOf(false) }
    var faceSinceNs by remember { mutableLongStateOf(0L) }
    var held by remember { mutableFloatStateOf(0f) } // seconds the face has been in view continuously
    var firstOkS by remember { mutableStateOf<Double?>(null) }
    var showSkip by remember { mutableStateOf(false) }

    DisposableEffect(Unit) {
        val camera = FaceCheckCamera(
            context,
            onFace = { visible ->
                if (visible && !face) faceSinceNs = Clocks.elapsedNs()
                face = visible
            },
            onUnavailable = { unavailable = true },
        )
        camera.start()
        onDispose { camera.stop() }
    }
    LaunchedEffect(Unit) {
        while (true) {
            held = if (face && faceSinceNs > 0) (Clocks.elapsedNs() - faceSinceNs) / 1e9f else 0f
            if (held >= minFaceS && firstOkS == null) firstOkS = (Clocks.elapsedNs() - startNs) / 1e9
            if (!showSkip && (Clocks.elapsedNs() - startNs) > 15_000_000_000L) showSkip = true
            delay(100)
        }
    }

    fun finish(ok: Boolean) {
        session.log.event(
            "camera_check", fields = arrayOf(
                "step_id" to step.id, "result" to if (ok) "ok" else "failed",
                "face_s" to firstOkS?.let { Math.round(it * 100) / 100.0 },
            )
        )
        onContinue()
    }

    val ready = firstOkS != null
    Column(
        Modifier.fillMaxSize().padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text("Camera check", fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(12.dp))
        Text(instructions, fontSize = 16.sp, textAlign = TextAlign.Center)
        Spacer(Modifier.height(28.dp))
        // framing guide: where the face should be; no video
        val guide = if (face) Color(0xFF2E7D32) else MaterialTheme.colorScheme.outline
        Canvas(Modifier.size(width = 200.dp, height = 260.dp)) {
            drawOval(
                guide, topLeft = Offset.Zero, size = Size(size.width, size.height),
                style = Stroke(width = 4.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(24f, 16f))),
            )
        }
        Spacer(Modifier.height(20.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(12.dp).background(if (face) Color(0xFF2E7D32) else Color(0xFFB0B0B0), CircleShape))
            Spacer(Modifier.width(8.dp))
            Text(
                when {
                    unavailable -> "Face detection isn't available on this phone"
                    face -> "Face detected"
                    else -> "Looking for a face…"
                },
                fontSize = 15.sp,
            )
        }
        Spacer(Modifier.height(12.dp))
        LinearProgressIndicator(progress = { (held / minFaceS.toFloat()).coerceIn(0f, 1f) }, modifier = Modifier.width(200.dp))
        Spacer(Modifier.height(24.dp))
        Button(onClick = { finish(true) }, enabled = ready) { Text("Continue") }
        if ((showSkip || unavailable) && !ready) {
            TextButton(onClick = { finish(false) }) { Text("Continue without face") }
        }
    }
}
