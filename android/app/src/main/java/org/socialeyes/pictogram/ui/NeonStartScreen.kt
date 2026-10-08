package org.socialeyes.pictogram.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * Shown to the researcher between "Start session" and the first step while the app starts the
 * Neon recording (neon.auto_record). If that fails it says why; "Continue without eye tracking"
 * is only offered when the study doesn't set neon.required.
 */
@Composable
fun NeonStartScreen(
    participantId: String,
    error: String?,
    required: Boolean,
    onRetry: () -> Unit,
    onContinueWithout: () -> Unit,
    onBack: () -> Unit,
) {
    Column(
        Modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        if (error == null) {
            CircularProgressIndicator()
            Text("Starting the eye-tracking recording for $participantId…", textAlign = TextAlign.Center)
            return@Column
        }
        Text("Eye tracking isn't ready", fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
        Text(error, textAlign = TextAlign.Center)
        Button(onClick = onRetry, modifier = Modifier.fillMaxWidth()) { Text("Try again") }
        if (!required) {
            OutlinedButton(onClick = onContinueWithout, modifier = Modifier.fillMaxWidth()) {
                Text("Continue without eye tracking")
            }
        } else {
            Text("This study needs the eye tracker (neon.required).", textAlign = TextAlign.Center)
        }
        TextButton(onClick = onBack) { Text("Back") }
    }
}
