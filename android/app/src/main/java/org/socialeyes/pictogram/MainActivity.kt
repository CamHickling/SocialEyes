package org.socialeyes.pictogram

import android.os.Bundle
import android.view.MotionEvent
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.socialeyes.pictogram.log.DeviceMonitor
import org.socialeyes.pictogram.log.InterruptionMonitor
import org.socialeyes.pictogram.neon.NeonClient
import org.socialeyes.pictogram.neon.NeonLink
import org.socialeyes.pictogram.neon.NeonSetup
import org.socialeyes.pictogram.neon.Preflight
import org.socialeyes.pictogram.study.StudyPackage
import org.socialeyes.pictogram.ui.NeonStartScreen
import org.socialeyes.pictogram.ui.SessionScreen
import org.socialeyes.pictogram.ui.SetupScreen
import java.io.File

/** A session waiting for its Neon recording: being checked (no preflight yet), waiting for the
 *  researcher, or starting; `error` says why it couldn't. */
private data class NeonPending(
    val pkg: StudyPackage,
    val participantId: String,
    val preflight: Preflight? = null,
    val starting: Boolean = false,
    val error: String? = null,
)

class MainActivity : ComponentActivity() {
    private var session by mutableStateOf<Session?>(null)
    private var neonPending by mutableStateOf<NeonPending?>(null)
    private var setupError by mutableStateOf<String?>(null)
    private var monitor: DeviceMonitor? = null
    private var interruptions: InterruptionMonitor? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val studiesDir = File(getExternalFilesDir(null), "studies").apply { mkdirs() }
        setContent {
            val s = session
            val pending = neonPending
            if (s == null && pending != null) {
                NeonStartScreen(
                    participantId = pending.participantId,
                    preflight = pending.preflight,
                    checklist = pending.pkg.study.neon.checklist,
                    starting = pending.starting,
                    error = pending.error,
                    required = pending.pkg.study.neon.required,
                    onStart = { answers -> startRecording(pending, answers) },
                    onRetry = { startSession(pending.pkg, pending.participantId) },
                    onContinueWithout = {
                        neonPending = null
                        val why = pending.error ?: pending.preflight?.problems?.joinToString("; ")
                        launchSession(pending.pkg, pending.participantId, null, notStarted = why)
                    },
                    onBack = { neonPending = null },
                )
            } else if (s == null) {
                SetupScreen(
                    studiesDir = studiesDir,
                    hasData = { study, pid -> Session.hasData(this, study, pid) },
                    error = setupError,
                    onStart = ::startSession,
                )
            } else {
                SessionScreen(s, onExit = ::endSession)
            }
        }
    }

    /** neon.auto_record: check the eye tracker, then (once the researcher confirms) start the
     *  Neon recording first, so the whole session is in it. */
    private fun startSession(pkg: StudyPackage, participantId: String) {
        if (!pkg.study.neon.autoRecord) {
            launchSession(pkg, participantId, null)
            return
        }
        neonPending = NeonPending(pkg, participantId)
        val values = mapOf(
            "participant_id" to participantId,
            "study_id" to pkg.study.id,
            "study_version" to pkg.study.version.toString(),
        )
        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) { runCatching { NeonSetup.check(NeonClient(), pkg.study.neon, values) } }
            neonPending = result.fold(
                onSuccess = { NeonPending(pkg, participantId, preflight = it) },
                onFailure = { e -> NeonPending(pkg, participantId, error = e.message ?: e.toString()) },
            )
        }
    }

    private fun startRecording(pending: NeonPending, checklist: List<Pair<String, Boolean>>) {
        val preflight = pending.preflight ?: return
        neonPending = pending.copy(starting = true)
        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) { runCatching { NeonLink.start(NeonClient(), preflight, checklist) } }
            result.fold(
                onSuccess = { neon ->
                    neonPending = null
                    launchSession(pending.pkg, pending.participantId, neon)
                },
                onFailure = { e -> neonPending = pending.copy(starting = false, error = e.message ?: e.toString()) },
            )
        }
    }

    /** `notStarted`: why the researcher chose to go on without the Neon recording. */
    private fun launchSession(pkg: StudyPackage, participantId: String, neon: NeonLink?, notStarted: String? = null) {
        val s = try {
            Session.create(this, pkg, participantId, neon)
        } catch (e: Exception) {
            neon?.stop("setup_failed")
            setupError = "Could not start the session: ${e.message}"
            return
        }
        if (notStarted != null) {
            s.log.event("neon", fields = arrayOf("status" to "disconnected", "reason" to "not_started", "error" to notStarted))
        }
        setupError = null
        hideSystemBars(true)
        monitor = DeviceMonitor(this, s.log).also { it.start() }
        interruptions = InterruptionMonitor(this, s.log).also { it.start() }
        session = s
        s.begin()
    }

    private fun endSession() {
        monitor?.stop()
        monitor = null
        interruptions?.stop()
        interruptions = null
        session?.let { if (!it.log.finished) it.abort() }
        session = null
        hideSystemBars(false)
    }

    /** Hides the status and navigation bars during a session; a swipe shows them briefly. */
    private fun hideSystemBars(on: Boolean) {
        val controller = WindowCompat.getInsetsController(window, window.decorView)
        if (on) {
            controller.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            controller.hide(WindowInsetsCompat.Type.systemBars())
        } else {
            controller.show(WindowInsetsCompat.Type.systemBars())
        }
    }

    // Every touch goes through here first, so touch.csv sees all of them.
    override fun dispatchTouchEvent(ev: MotionEvent): Boolean {
        session?.takeIf { !it.log.finished }?.touches?.record(ev)
        return super.dispatchTouchEvent(ev)
    }

    override fun onStart() {
        super.onStart()
        session?.log?.event("app_state", fields = arrayOf("state" to "foreground"))
        session?.resumeCamera()
    }

    override fun onStop() {
        interruptions?.leftScreen()
        session?.log?.event("app_state", fields = arrayOf("state" to "background"))
        session?.pauseCamera()
        super.onStop()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        interruptions?.windowFocus(hasFocus)
    }

    override fun onDestroy() {
        if (isFinishing) endSession()
        super.onDestroy()
    }
}
