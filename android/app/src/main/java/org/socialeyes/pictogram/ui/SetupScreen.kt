package org.socialeyes.pictogram.ui

import org.socialeyes.pictogram.log.InterruptionMonitor
import kotlinx.coroutines.delay
import androidx.compose.runtime.LaunchedEffect
import android.provider.Settings
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import android.content.Intent
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.pm.ShortcutInfoCompat
import androidx.core.content.pm.ShortcutManagerCompat
import androidx.core.graphics.drawable.IconCompat
import org.socialeyes.pictogram.BuildConfig
import org.socialeyes.pictogram.MainActivity
import org.socialeyes.pictogram.R
import org.socialeyes.pictogram.study.StudyPackage
import org.socialeyes.pictogram.study.flag
import java.io.File

/** Asks the launcher to put a Pictogram shortcut on the home screen (it shows its own confirmation). */
private fun requestHomeScreenShortcut(context: Context) {
    val intent = Intent(context, MainActivity::class.java).setAction(Intent.ACTION_MAIN)
    val shortcut = ShortcutInfoCompat.Builder(context, "launch")
        .setShortLabel(context.getString(R.string.app_name))
        .setIcon(IconCompat.createWithResource(context, R.mipmap.ic_launcher))
        .setIntent(intent)
        .build()
    ShortcutManagerCompat.requestPinShortcut(context, shortcut, null)
}

/** Researcher screen: pick a study package and a participant, then start the session. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SetupScreen(
    studiesDir: File,
    hasData: (studyId: String, participantId: String) -> Boolean,
    error: String?,
    onStart: (StudyPackage, String) -> Unit,
) {
    var studies by remember { mutableStateOf(StudyPackage.findAll(studiesDir)) }
    var selectedDir by remember { mutableStateOf(studies.firstOrNull { it.second.isSuccess }?.first) }
    var participant by remember { mutableStateOf<String?>(null) }
    var confirmRepeat by remember { mutableStateOf(false) }
    val pkg = studies.firstOrNull { it.first == selectedDir }?.second?.getOrNull()

    MaterialTheme {
        Surface(Modifier.fillMaxSize()) {
            Column(
                Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("SocialEyes", fontSize = 26.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                    Text("v${BuildConfig.VERSION_NAME}", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                error?.let { Text(it, color = MaterialTheme.colorScheme.error) }

                if (studies.isEmpty()) {
                    Text("No study packages found. Compile a study on your computer and copy it to the phone:")
                    SelectionContainer {
                        Text(
                            "socialeyes compile studies/my_study\n" +
                                "adb push build/my_study ${studiesDir.absolutePath.replace("/storage/emulated/0", "/sdcard")}/",
                            fontFamily = FontFamily.Monospace, fontSize = 13.sp,
                        )
                    }
                }

                if (studies.isNotEmpty()) Text("Study", fontWeight = FontWeight.SemiBold)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    studies.forEach { (dir, result) ->
                        FilterChip(
                            selected = dir == selectedDir,
                            onClick = { selectedDir = dir; participant = null },
                            label = { Text(dir.name) },
                            enabled = result.isSuccess,
                        )
                    }
                }
                studies.filter { it.second.isFailure }.forEach { (dir, result) ->
                    Text("${dir.name}: ${result.exceptionOrNull()?.message}", color = MaterialTheme.colorScheme.error, fontSize = 13.sp)
                }

                if (pkg != null) {
                    Text("${pkg.study.title} (id ${pkg.study.id}, version ${pkg.study.version})")
                    pkg.unsupportedFeatures().takeIf { it.isNotEmpty() }?.let { notes ->
                        Text("Not supported by this app version yet:", color = MaterialTheme.colorScheme.error, fontSize = 13.sp)
                        notes.forEach { Text("• $it", fontSize = 13.sp) }
                    }
                    // Ask for the camera here, so participants never see Android's permission dialog.
                    val cameraSettings = pkg.study.logging["front_camera"] as? kotlinx.serialization.json.JsonObject
                    val usesCamera = pkg.steps.any { it.type == "profile_photo" || it.type == "camera_check" } ||
                        cameraSettings?.flag("enabled", false) == true
                    if (usesCamera) {
                        val context = LocalContext.current
                        var cameraOk by remember {
                            mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED)
                        }
                        val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { cameraOk = it }
                        if (!cameraOk) {
                            Text("This study uses the front camera. Allow camera access now, so participants don't see Android's permission prompt.",
                                fontSize = 13.sp)
                            OutlinedButton(onClick = { ask.launch(Manifest.permission.CAMERA) }) { Text("Allow camera") }
                        }
                    }
                    DndHint()
                    Spacer(Modifier.height(4.dp))
                    Text("Participant (✓ = has data already)", fontWeight = FontWeight.SemiBold)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        pkg.participantIds().forEach { pid ->
                            val done = hasData(pkg.study.id, pid)
                            FilterChip(
                                selected = pid == participant,
                                onClick = { participant = pid },
                                label = { Text(if (done) "$pid ✓" else pid) },
                            )
                        }
                    }
                    Button(
                        onClick = {
                            val pid = participant ?: return@Button
                            if (hasData(pkg.study.id, pid)) confirmRepeat = true else onStart(pkg, pid)
                        },
                        enabled = participant != null,
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text(participant?.let { "Start session for $it" } ?: "Choose a participant") }
                }

                OutlinedButton(onClick = {
                    studies = StudyPackage.findAll(studiesDir)
                    if (studies.none { it.first == selectedDir }) selectedDir = studies.firstOrNull { it.second.isSuccess }?.first
                }) { Text("Reload studies") }
                val context = LocalContext.current
                if (ShortcutManagerCompat.isRequestPinShortcutSupported(context)) {
                    OutlinedButton(onClick = { requestHomeScreenShortcut(context) }) { Text("Add to home screen") }
                }
                Text(
                    "Sessions are saved in Android/data/${BuildConfig.APPLICATION_ID}/files/data/. " +
                        "Press Back during a session to stop it.",
                    color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 13.sp,
                )
            }

            if (confirmRepeat && pkg != null && participant != null) {
                AlertDialog(
                    onDismissRequest = { confirmRepeat = false },
                    title = { Text("$participant already has data") },
                    text = { Text("Start another session for this participant? The earlier session is kept.") },
                    confirmButton = {
                        TextButton(onClick = { confirmRepeat = false; onStart(pkg, participant!!) }) { Text("Start") }
                    },
                    dismissButton = { TextButton(onClick = { confirmRepeat = false }) { Text("Cancel") } },
                )
            }
        }
    }
}

/** Reminds the researcher to turn on Do Not Disturb; re-checked while the screen is open. */
@Composable
private fun DndHint() {
    val context = LocalContext.current
    var dndOn by remember { mutableStateOf(InterruptionMonitor.dndOn(context)) }
    LaunchedEffect(Unit) {
        while (true) {
            dndOn = InterruptionMonitor.dndOn(context)
            delay(1000)
        }
    }
    if (dndOn) return
    Text("Do Not Disturb is off. Turn it on so notifications and calls don't interrupt the session.",
        fontSize = 13.sp)
    OutlinedButton(onClick = {
        val zen = Intent("android.settings.ZEN_MODE_SETTINGS")
        runCatching { context.startActivity(zen) }.onFailure {
            context.startActivity(Intent(Settings.ACTION_SOUND_SETTINGS))
        }
    }) { Text("Open Do Not Disturb settings") }
}
