package org.socialeyes.pictogram.log

import android.os.Build
import android.view.MotionEvent

/**
 * Writes every touch sample to touch.csv. Called from Activity.dispatchTouchEvent,
 * so it sees all touches before any view handles them.
 *
 * Batched (historical) samples of a MOVE each get their own row and time.
 */
class TouchRecorder(private val log: SessionLog, private val stepId: () -> String) {

    fun record(ev: MotionEvent) {
        val offset = Clocks.monotonicOffsetNs()
        // getRawX/Y exist per pointer, but not for historical samples: shift
        // window coordinates by the window's offset on screen instead.
        val dx = ev.rawX - ev.x
        val dy = ev.rawY - ev.y
        val step = stepId()

        fun current(action: String, i: Int) = log.touchRow(
            eventNs(ev) + offset, action, ev.getPointerId(i), ev.getX(i) + dx, ev.getY(i) + dy,
            ev.getPressure(i), ev.getSize(i), ev.getTouchMajor(i).orNull(), ev.getTouchMinor(i).orNull(), step,
        )

        when (ev.actionMasked) {
            MotionEvent.ACTION_DOWN, MotionEvent.ACTION_POINTER_DOWN -> current("down", ev.actionIndex)
            MotionEvent.ACTION_UP, MotionEvent.ACTION_POINTER_UP -> current("up", ev.actionIndex)
            MotionEvent.ACTION_CANCEL -> for (i in 0 until ev.pointerCount) current("cancel", i)
            MotionEvent.ACTION_MOVE -> {
                for (h in 0 until ev.historySize) {
                    val t = historicalNs(ev, h) + offset
                    for (i in 0 until ev.pointerCount) {
                        log.touchRow(
                            t, "move", ev.getPointerId(i), ev.getHistoricalX(i, h) + dx, ev.getHistoricalY(i, h) + dy,
                            ev.getHistoricalPressure(i, h), ev.getHistoricalSize(i, h),
                            ev.getHistoricalTouchMajor(i, h).orNull(), ev.getHistoricalTouchMinor(i, h).orNull(), step,
                        )
                    }
                }
                for (i in 0 until ev.pointerCount) current("move", i)
            }
        }
    }

    private fun Float.orNull() = takeIf { it > 0f }

    private fun eventNs(ev: MotionEvent) =
        if (Build.VERSION.SDK_INT >= 34) ev.eventTimeNanos else ev.eventTime * 1_000_000

    private fun historicalNs(ev: MotionEvent, h: Int) =
        if (Build.VERSION.SDK_INT >= 34) ev.getHistoricalEventTimeNanos(h) else ev.getHistoricalEventTime(h) * 1_000_000
}
