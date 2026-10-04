package org.socialeyes.pictogram.log

import android.app.NotificationManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.AudioPlaybackConfiguration
import android.os.Handler
import android.os.Looper

/**
 * `interruption` events (docs/EVENT_LOG.md, "Session quality"), from what Android
 * shows an app without special permissions:
 *  - `notification`: a notification sound is playing (silent and vibrate-only
 *    notifications can't be seen; turn on Do Not Disturb for sessions)
 *  - `call`: the phone is ringing or a call is active
 *  - `alarm`: an alarm or timer is sounding
 *  - `focus_lost`: something covered the app without it leaving the screen
 *    (notification shade, system dialog, power menu)
 * Each has a `start` and an `end` event. Also logs `dnd` (Do Not Disturb) at the
 * start and on every change.
 */
class InterruptionMonitor(private val context: Context, private val log: SessionLog) {
    private val handler = Handler(Looper.getMainLooper())
    private val audio = context.getSystemService(AudioManager::class.java)
    private val notifications = context.getSystemService(NotificationManager::class.java)

    private var fromAudio = emptySet<String>() // kinds of sound playing now
    private var inCall = false                // from the audio mode
    private var focusLost = false
    private var focusLostNs = 0L
    private var active = emptySet<String>()

    // Going to the home screen also takes the focus, just before onStop; only count a
    // focus loss once the app is still on screen half a second later.
    private val focusCheck = Runnable {
        focusLost = true
        update(focusLostNs)
    }

    private val playbackCallback = object : AudioManager.AudioPlaybackCallback() {
        override fun onPlaybackConfigChanged(configs: MutableList<AudioPlaybackConfiguration>) {
            fromAudio = configs.mapNotNull { kindOf(it.audioAttributes.usage) }.toSet()
            update()
        }
    }

    // AudioManager has a mode listener only from API 31; checking once a second is cheap.
    private val modeTick = object : Runnable {
        override fun run() {
            inCall = audio.mode in CALL_MODES
            update()
            handler.postDelayed(this, 1000)
        }
    }

    private val dndReceiver = object : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) = logDnd()
    }

    fun start() {
        logDnd()
        context.registerReceiver(dndReceiver, IntentFilter(NotificationManager.ACTION_INTERRUPTION_FILTER_CHANGED))
        audio.registerAudioPlaybackCallback(playbackCallback, handler)
        playbackCallback.onPlaybackConfigChanged(audio.activePlaybackConfigurations)
        modeTick.run()
    }

    fun stop() {
        handler.removeCallbacks(modeTick)
        handler.removeCallbacks(focusCheck)
        audio.unregisterAudioPlaybackCallback(playbackCallback)
        runCatching { context.unregisterReceiver(dndReceiver) }
    }

    /** From Activity.onWindowFocusChanged. */
    fun windowFocus(hasFocus: Boolean) {
        handler.removeCallbacks(focusCheck)
        if (hasFocus) {
            focusLost = false
            update()
        } else {
            focusLostNs = Clocks.elapsedNs()
            handler.postDelayed(focusCheck, 500)
        }
    }

    /** From Activity.onStop: the app left the screen (`app_state` covers that), not a focus loss. */
    fun leftScreen() {
        handler.removeCallbacks(focusCheck)
        focusLost = false
        update()
    }

    private fun update(tNs: Long = Clocks.elapsedNs()) {
        val now = buildSet {
            addAll(fromAudio)
            if (inCall) add("call")
            if (focusLost) add("focus_lost")
        }
        (now - active).forEach { log.event("interruption", tNs, "kind" to it, "phase" to "start") }
        (active - now).forEach { log.event("interruption", tNs, "kind" to it, "phase" to "end") }
        active = now
    }

    private fun logDnd() {
        val filter = when (notifications.currentInterruptionFilter) {
            NotificationManager.INTERRUPTION_FILTER_ALL -> "off"
            NotificationManager.INTERRUPTION_FILTER_PRIORITY -> "priority"
            NotificationManager.INTERRUPTION_FILTER_ALARMS -> "alarms"
            NotificationManager.INTERRUPTION_FILTER_NONE -> "total_silence"
            else -> "unknown"
        }
        log.event("dnd", fields = arrayOf("filter" to filter))
    }

    companion object {
        private val CALL_MODES = setOf(
            AudioManager.MODE_RINGTONE, AudioManager.MODE_IN_CALL,
            AudioManager.MODE_IN_COMMUNICATION, AudioManager.MODE_CALL_SCREENING,
        )

        @Suppress("DEPRECATION") // the NOTIFICATION_COMMUNICATION_* usages are still sent by older apps
        private fun kindOf(usage: Int): String? = when (usage) {
            AudioAttributes.USAGE_NOTIFICATION, AudioAttributes.USAGE_NOTIFICATION_EVENT,
            AudioAttributes.USAGE_NOTIFICATION_COMMUNICATION_INSTANT,
            AudioAttributes.USAGE_NOTIFICATION_COMMUNICATION_DELAYED,
            AudioAttributes.USAGE_NOTIFICATION_COMMUNICATION_REQUEST -> "notification"
            AudioAttributes.USAGE_NOTIFICATION_RINGTONE, AudioAttributes.USAGE_VOICE_COMMUNICATION -> "call"
            AudioAttributes.USAGE_ALARM -> "alarm"
            else -> null // media (including the app's own reels), games, navigation, ...
        }

        /** Do Not Disturb as `dnd` events name it; for the setup screen. */
        fun dndOn(context: Context) =
            context.getSystemService(NotificationManager::class.java).currentInterruptionFilter !=
                NotificationManager.INTERRUPTION_FILTER_ALL
    }
}
