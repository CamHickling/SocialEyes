package org.socialeyes.pictogram.ui

import org.socialeyes.pictogram.log.InterruptionMonitor
import kotlinx.coroutines.delay
import androidx.compose.runtime.LaunchedEffect
import android.provider.Settings
import android.os.BatteryManager
import android.os.StatFs
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
import androidx.compose.material3.Switch
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
    pinSessions: Boolean = false,
    onPinSessions: (Boolean) -> Unit = {},
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
                    ReadyCheck()
                    DndHint()
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Pin the app during sessions", modifier = Modifier.weight(1f), fontSize = 14.sp)
                        Switch(checked = pinSessions, onCheckedChange = onPinSessions)
                    }
                    Text("Pinned, a participant can't leave the app by accident. Android asks to confirm at the start " +
                        "of each session, and may lock the phone when the session ends (Settings > Security > App " +
                        "pinning > Ask for PIN before unpinning).", fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.height(4.dp))
                    // ids with data on this phone, or that the computer's register has seen; withdrawn ones can't be chosen
                    val (used, withdrawn) = remember(pkg) { pkg.usedIds() }
                    val ids = pkg.participantIds()
                    val taken = { pid: String -> pid in used || hasData(pkg.study.id, pid) }
                    val next = ids.firstOrNull { !taken(it) && it !in withdrawn }
                    if (next != null) {
                        Button(onClick = { onStart(pkg, next) }, modifier = Modifier.fillMaxWidth()) {
                            Text("Start the next participant: $next", fontSize = 16.sp)
                        }
                    } else {
                        Text("Every participant id of this study has been used. Make more plans on the computer and load the study again.",
                            color = MaterialTheme.colorScheme.error, fontSize = 13.sp)
                    }
                    Text("Or choose (✓ = used already)", fontWeight = FontWeight.SemiBold)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        ids.forEach { pid ->
                            val gone = pid in withdrawn
                            FilterChip(
                                selected = pid == participant,
                                onClick = { participant = pid },
                                enabled = !gone,
                                label = { Text(if (gone) "$pid withdrawn" else if (taken(pid)) "$pid ✓" else pid) },
                            )
                        }
                    }
                    Button(
                        onClick = {
                            val pid = participant ?: return@Button
                            val (used, _) = pkg.usedIds()
                            if (pid in used || hasData(pkg.study.id, pid)) confirmRepeat = true else onStart(pkg, pid)
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
                    title = { Text("$participant has been used already") },
                    text = { Text("This id has a session on this phone or on the computer. Start another session for it? " +
                        "The earlier session is kept; giving each participant a new id is usually better.") },
                    confirmButton = {
                        TextButton(onClick = { confirmRepeat = false; onStart(pkg, participant!!) }) { Text("Start") }
                    },
                    dismissButton = { TextButton(onClick = { confirmRepeat = false }) { Text("Cancel") } },
                )
            }
        }
    }
}

/** Battery and free storage before a session: warns when either is low. */
@Composable
private fun ReadyCheck() {
    val context = LocalContext.current
    var battery by remember { mutableStateOf<Pair<Int, Boolean>?>(null) }
    var freeGb by remember { mutableStateOf<Double?>(null) }
    LaunchedEffect(Unit) {
        while (true) {
            val bm = context.getSystemService(BatteryManager::class.java)
            battery = bm?.let { it.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY) to it.isCharging }
            freeGb = context.getExternalFilesDir(null)?.let { StatFs(it.path).availableBytes / 1e9 }
            delay(5000)
        }
    }
    val warn = MaterialTheme.colorScheme.error
    val ok = MaterialTheme.colorScheme.onSurfaceVariant
    battery?.let { (pct, charging) ->
        val low = pct < 50 && !charging
        Text("Battery ${pct}%${if (charging) " (charging)" else ""}${if (low) ": charge it before the session" else ""}",
            fontSize = 13.sp, color = if (low) warn else ok)
    }
    freeGb?.let { gb ->
        val low = gb < 2.0
        Text("Storage ${"%.1f".format(gb)} GB free${if (low) ": copy and clear sessions on the computer first" else ""}",
            fontSize = 13.sp, color = if (low) warn else ok)
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
