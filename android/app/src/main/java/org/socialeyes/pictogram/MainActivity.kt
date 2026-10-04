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
import org.socialeyes.pictogram.log.DeviceMonitor
import org.socialeyes.pictogram.study.StudyPackage
import org.socialeyes.pictogram.ui.SessionScreen
import org.socialeyes.pictogram.ui.SetupScreen
import java.io.File

class MainActivity : ComponentActivity() {
    private var session by mutableStateOf<Session?>(null)
    private var setupError by mutableStateOf<String?>(null)
    private var monitor: DeviceMonitor? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val studiesDir = File(getExternalFilesDir(null), "studies").apply { mkdirs() }
        setContent {
            val s = session
            if (s == null) {
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

    private fun startSession(pkg: StudyPackage, participantId: String) {
        val s = try {
            Session.create(this, pkg, participantId)
        } catch (e: Exception) {
            setupError = "Could not start the session: ${e.message}"
            return
        }
        setupError = null
        hideSystemBars(true)
        monitor = DeviceMonitor(this, s.log).also { it.start() }
        session = s
        s.begin()
    }

    private fun endSession() {
        monitor?.stop()
        monitor = null
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
        session?.log?.event("app_state", fields = arrayOf("state" to "background"))
        session?.pauseCamera()
        super.onStop()
    }

    override fun onDestroy() {
        if (isFinishing) endSession()
        super.onDestroy()
    }
}
