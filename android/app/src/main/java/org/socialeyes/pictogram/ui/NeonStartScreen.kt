package org.socialeyes.pictogram.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.socialeyes.pictogram.neon.Preflight

/**
 * Shown to the researcher between "Start session" and the first step (neon.auto_record):
 * first what Companion reports (glasses, battery, storage, streams, the scene camera exposure and
 * template fields the study will set) and the study's checklist, then "Start recording".
 * If something is wrong it says why; "Continue without eye tracking" is only offered when the
 * study doesn't set neon.required.
 */
@Composable
fun NeonStartScreen(
    participantId: String,
    preflight: Preflight?,
    checklist: List<String>,
    starting: Boolean,
    error: String?,
    required: Boolean,
    /** The phone's address for `socialeyes calibrate-display`, when the study has a display calibration. */
    laptopAddress: String? = null,
    onStart: (List<Pair<String, Boolean>>) -> Unit,
    onRetry: () -> Unit,
    onContinueWithout: () -> Unit,
    onBack: () -> Unit,
) {
    val ticked = remember(checklist) { mutableStateListOf(*Array(checklist.size) { false }) }
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(32.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        when {
            error != null -> {
                Text("Eye tracking isn't ready", fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
                Text(error, textAlign = TextAlign.Center)
                Button(onClick = onRetry, modifier = Modifier.fillMaxWidth()) { Text("Check again") }
                if (!required) {
                    OutlinedButton(onClick = onContinueWithout, modifier = Modifier.fillMaxWidth()) {
                        Text("Continue without eye tracking")
                    }
                } else {
                    Text("This study needs the eye tracker (neon.required).", textAlign = TextAlign.Center)
                }
                TextButton(onClick = onBack) { Text("Back") }
            }
            preflight == null || starting -> {
                CircularProgressIndicator()
                Text(
                    if (starting) "Starting the eye-tracking recording for $participantId…" else "Checking the eye tracker…",
                    textAlign = TextAlign.Center,
                )
            }
            else -> {
                Text("Eye tracker: $participantId", fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
                val s = preflight.status
                Info("Glasses", s.moduleSerial?.let { "connected (module $it${s.frameName?.let { f -> ", $f" } ?: ""})" } ?: "not connected")
                Info("Phone", listOfNotNull(s.batteryLevel?.let { "battery $it%" }, s.memoryState?.let { "storage $it" }).joinToString(", ").ifEmpty { "-" })
                if (s.streams.isNotEmpty()) {
                    Info("Streams", listOf("gaze", "world").joinToString(", ") { k ->
                        "${if (k == "world") "scene" else k} ${if (s.streams[k] == true) "OK" else "not yet"}"
                    })
                }
                preflight.camera?.let { cam ->
                    Info("Scene camera", cam.entries.joinToString(", ") { (k, c) -> "$k ${c.current}" } +
                        if (preflight.exposureChange.isEmpty()) "" else
                            "\n→ the study sets " + preflight.exposureChange.entries.joinToString(", ") { (k, v) -> "$k $v" } +
                                " (put back afterwards)")
                }
                if (preflight.templateFilled.isNotEmpty()) Info("Template", "fills " + preflight.templateFilled.joinToString())
                laptopAddress?.let { Info("Calibration", "on the laptop: socialeyes calibrate-display $it") }
                preflight.problems.forEach { Text("✗ $it", color = MaterialTheme.colorScheme.error) }
                preflight.warnings.forEach { Text("! $it", color = MaterialTheme.colorScheme.tertiary) }
                checklist.forEachIndexed { i, item ->
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(checked = ticked[i], onCheckedChange = { ticked[i] = it })
                        Text(item)
                    }
                }
                Button(
                    onClick = { onStart(checklist.mapIndexed { i, item -> item to ticked[i] }) },
                    enabled = preflight.ready && ticked.all { it },
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Start recording") }
                OutlinedButton(onClick = onRetry, modifier = Modifier.fillMaxWidth()) { Text("Check again") }
                if (!required && !preflight.ready) {
                    OutlinedButton(onClick = onContinueWithout, modifier = Modifier.fillMaxWidth()) {
                        Text("Continue without eye tracking")
                    }
                }
                TextButton(onClick = onBack) { Text("Back") }
            }
        }
    }
}

@Composable
private fun Info(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(label, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(end = 4.dp))
        Text(value)
    }
}
