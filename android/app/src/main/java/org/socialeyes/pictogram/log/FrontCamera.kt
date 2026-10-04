package org.socialeyes.pictogram.log

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.ImageFormat
import android.hardware.HardwareBuffer
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.CaptureResult
import android.hardware.camera2.TotalCaptureResult
import android.media.ImageReader
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.MediaMuxer
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import android.util.Range
import android.util.Size
import android.util.Log
import android.view.Surface
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.io.File
import java.util.TreeMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.math.abs

/** Settings from the study's `logging.front_camera`. */
data class FrontCameraConfig(
    val resolution: String = "720p",
    val fps: Int = 30,
    val bitrateMbps: Double = 3.0,
    val steps: List<String>? = listOf("feed"), // null = all steps
    val segmentS: Int = 60,
) {
    fun records(stepId: String) = steps == null || stepId in steps
}

/** The front camera's id, sensor orientation and timestamp base. */
private class FrontCameraInfo(val id: String, val chars: CameraCharacteristics) {
    val orientation: Int = chars.get(CameraCharacteristics.SENSOR_ORIENTATION) ?: 270
    val realtime: Boolean = chars.get(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE) ==
        CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME

    companion object {
        fun find(manager: CameraManager): FrontCameraInfo? = manager.cameraIdList
            .map { FrontCameraInfo(it, manager.getCameraCharacteristics(it)) }
            .firstOrNull { it.chars.get(CameraCharacteristics.LENS_FACING) == CameraCharacteristics.LENS_FACING_FRONT }
    }
}

/**
 * Records the front camera into H.264 MP4 segments with one `camera_frames.csv`
 * row per encoded frame (docs/EVENT_LOG.md, "Front camera"). The camera feeds the
 * encoder's input surface directly, so each encoded frame carries the camera's
 * SENSOR_TIMESTAMP; rows are written for exactly the frames that go into each file,
 * so frame numbers always match the video. No preview is ever shown.
 *
 * Thread-safe; camera and encoder work runs on a background thread.
 */
private const val TAG = "SocialEyesCamera"

class FrontCameraRecorder(context: Context, private val dir: File, private val log: SessionLog, val config: FrontCameraConfig) {
    private val manager = context.getSystemService(CameraManager::class.java)
    private val thread = HandlerThread("front-camera").apply { start() }
    private val handler = Handler(thread.looper)
    private val info = FrontCameraInfo.find(manager)

    // touched only on the camera thread
    private var device: CameraDevice? = null
    private var session: CameraCaptureSession? = null
    private var encoder: MediaCodec? = null
    private var inputSurface: Surface? = null
    // An invisible preview-like stream next to the encoder. Some drivers (the Pixel 3's)
    // only run a video stream alongside a preview, and lose every frame otherwise.
    private var previewSink: ImageReader? = null
    private var muxer: MediaMuxer? = null
    private var track = -1
    private var outputFormat: MediaFormat? = null
    private var segment = -1
    private var frameInSegment = 0
    private var segmentStartUs = -1L
    private var splitPending = false
    private var closing = false
    private var closeStatus = "stopped"
    private var closeLatch: CountDownLatch? = null
    // Recent capture results: SENSOR_TIMESTAMP -> exposure time (null if not reported).
    // Only touched on the camera thread.
    private val captured = TreeMap<Long, Long?>()
    // Encoded frame time + this = SENSOR_TIMESTAMP. Android shifts video-encoder streams
    // from the boot clock to the monotonic clock, so it isn't always 0; found on the first frame.
    private var ptsToSensorNs: Long? = null

    @Volatile
    var recording = false
        private set

    val available get() = info != null

    /** Starts recording (a new segment), unless it already is. */
    fun start() = handler.post { if (!recording) open() }

    /**
     * Stops recording and closes the current segment. With [wait], blocks until the
     * file is closed (max 2 s): needed before the log ends or the app is backgrounded,
     * not between steps, where it would freeze the screen.
     */
    fun stop(wait: Boolean = true) {
        val done = CountDownLatch(1)
        handler.post {
            if (encoder == null && device == null) done.countDown() else {
                closeLatch = done
                close("stopped")
            }
        }
        if (wait) done.await(2, TimeUnit.SECONDS)
    }

    fun release() {
        stop()
        thread.quitSafely()
    }

    // ------------------------------------------------------------ camera thread

    @SuppressLint("MissingPermission") // the setup screen asks for the camera
    private fun open() {
        val cam = info ?: return error("no front camera")
        if (closing) finishClose() // restarted before the last file finished flushing
        try {
            ptsToSensorNs = null // the clock offset can change while the phone sleeps
            captured.clear()
            val size = chooseSize(cam)
            val fpsRange = chooseFps(cam)
            val enc = createEncoder(size)
            recording = true
            log.setMeta("camera", buildJsonObject {
                put("lens", "front")
                put("width", size.width)
                put("height", size.height)
                put("fps", fpsRange.upper)
                put("timestamp_source", if (cam.realtime) "realtime" else "unknown")
                put("orientation", cam.orientation)
            })
            manager.openCamera(cam.id, object : CameraDevice.StateCallback() {
                override fun onOpened(d: CameraDevice) {
                    device = d
                    startSession(d, enc, fpsRange)
                }

                override fun onDisconnected(d: CameraDevice) {
                    d.close()
                    close("stopped", "camera disconnected")
                }

                override fun onError(d: CameraDevice, code: Int) {
                    d.close()
                    close("stopped", "camera error $code")
                }
            }, handler)
        } catch (e: Exception) {
            error(e.message ?: e.toString())
            close("stopped")
        }
    }

    @Suppress("DEPRECATION") // createCaptureSession(List<Surface>, ...) is fine on API 29+
    private fun startSession(d: CameraDevice, enc: MediaCodec, fps: Range<Int>) {
        val surface = inputSurface ?: return
        val sink = ImageReader.newInstance(
            640, 480, ImageFormat.PRIVATE, 2, HardwareBuffer.USAGE_GPU_SAMPLED_IMAGE,
        ).also { previewSink = it }
        sink.setOnImageAvailableListener({ r -> r.acquireLatestImage()?.close() }, handler) // never shown
        d.createCaptureSession(listOf(surface, sink.surface), object : CameraCaptureSession.StateCallback() {
            override fun onConfigured(s: CameraCaptureSession) {
                session = s
                val request = d.createCaptureRequest(CameraDevice.TEMPLATE_RECORD).apply {
                    addTarget(surface)
                    addTarget(sink.surface)
                    set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, fps)
                }.build()
                s.setRepeatingRequest(request, object : CameraCaptureSession.CaptureCallback() {
                    override fun onCaptureCompleted(s: CameraCaptureSession, r: CaptureRequest, result: TotalCaptureResult) {
                        val ts = result.get(CaptureResult.SENSOR_TIMESTAMP) ?: return
                        captured[ts] = result.get(CaptureResult.SENSOR_EXPOSURE_TIME)
                        while (captured.size > 120) captured.pollFirstEntry() // ~4 s at 30 fps
                    }
                }, handler)
            }

            override fun onConfigureFailed(s: CameraCaptureSession) {
                close("stopped", "camera session could not be configured")
            }
        }, handler)
    }

    private fun createEncoder(size: Size): MediaCodec {
        val format = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, size.width, size.height).apply {
            setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
            setInteger(MediaFormat.KEY_BIT_RATE, (config.bitrateMbps * 1_000_000).toInt())
            setInteger(MediaFormat.KEY_FRAME_RATE, config.fps)
            setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1) // a keyframe each second: segments can start promptly
        }
        val enc = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC)
        enc.setCallback(object : MediaCodec.Callback() {
            override fun onInputBufferAvailable(c: MediaCodec, index: Int) {} // surface input
            override fun onOutputFormatChanged(c: MediaCodec, f: MediaFormat) {
                outputFormat = f
                newSegment()
            }

            override fun onOutputBufferAvailable(c: MediaCodec, index: Int, bi: MediaCodec.BufferInfo) {
                val last = bi.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0
                writeFrame(c, index, bi)
                if (last) finishClose() // the encoder has flushed its last frames
            }

            override fun onError(c: MediaCodec, e: MediaCodec.CodecException) {
                error("encoder: ${e.diagnosticInfo}")
            }
        }, handler)
        enc.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        inputSurface = enc.createInputSurface()
        enc.start()
        encoder = enc
        return enc
    }

    private fun writeFrame(c: MediaCodec, index: Int, bi: MediaCodec.BufferInfo) {
        val isConfig = bi.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0
        val isKey = bi.flags and MediaCodec.BUFFER_FLAG_KEY_FRAME != 0
        if (isConfig || bi.size == 0 || muxer == null) {
            c.releaseOutputBuffer(index, false)
            return
        }
        if (splitPending && isKey) newSegment()
        if (segmentStartUs < 0) {
            if (!isKey) { // a file must begin with a keyframe
                c.releaseOutputBuffer(index, false)
                return
            }
            segmentStartUs = bi.presentationTimeUs
        }
        val buffer = c.getOutputBuffer(index) ?: return c.releaseOutputBuffer(index, false)
        val sensorUs = bi.presentationTimeUs
        val out = MediaCodec.BufferInfo().apply { set(bi.offset, bi.size, sensorUs - segmentStartUs, bi.flags) }
        muxer?.writeSampleData(track, buffer, out)
        c.releaseOutputBuffer(index, false)

        val (tNs, exposureNs) = sensorTime(sensorUs * 1000)
        log.cameraFrameRow(segment, frameInSegment, tNs, exposureNs)
        frameInSegment++

        if (!splitPending && sensorUs - segmentStartUs >= config.segmentS * 1_000_000L) {
            splitPending = true
            c.setParameters(Bundle().apply { putInt(MediaCodec.PARAMETER_KEY_REQUEST_SYNC_FRAME, 0) })
        }
    }

    /**
     * The capture result belonging to an encoded frame: its SENSOR_TIMESTAMP (the session
     * clock when the source is realtime) and exposure. The encoder sees the timestamp
     * rounded to microseconds and possibly shifted to the monotonic clock, so match the
     * nearest result within 1 ms; without one, fall back to the shifted time itself.
     */
    private fun sensorTime(ptsNs: Long): Pair<Long, Long?> {
        fun match(guess: Long): Map.Entry<Long, Long?>? =
            listOfNotNull(captured.floorEntry(guess), captured.ceilingEntry(guess))
                .minByOrNull { abs(it.key - guess) }?.takeIf { abs(it.key - guess) <= 1_000_000L }
        val offset = ptsToSensorNs ?: listOf(0L, SystemClock.elapsedRealtimeNanos() - System.nanoTime())
            .firstOrNull { match(ptsNs + it) != null }?.also { ptsToSensorNs = it }
        val guess = ptsNs + (offset ?: (SystemClock.elapsedRealtimeNanos() - System.nanoTime()))
        val hit = match(guess) ?: return guess to null
        captured.remove(hit.key)
        return hit.key to hit.value
    }

    /** Closes the current file (if any) and starts the next one: front_000.mp4, front_001.mp4, ... */
    private fun newSegment() {
        val first = muxer == null
        closeMuxer()
        val format = outputFormat ?: return
        segment = log.nextCameraSegment()
        val name = "camera/front_%03d.mp4".format(segment)
        val file = File(dir, name).apply { parentFile?.mkdirs() }
        muxer = MediaMuxer(file.path, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4).also {
            it.setOrientationHint(info?.orientation ?: 270) // phone held upright
            track = it.addTrack(format)
            it.start()
        }
        frameInSegment = 0
        segmentStartUs = -1
        splitPending = false
        log.event("camera", fields = arrayOf("status" to if (first) "started" else "segment", "file" to name))
    }

    private fun closeMuxer() {
        val m = muxer ?: return
        muxer = null
        runCatching { if (frameInSegment > 0) m.stop() }
        runCatching { m.release() }
    }

    /**
     * Stops the camera and asks the encoder to flush; the file is closed in
     * [finishClose] once the encoder reports end of stream (or after 700 ms).
     */
    private fun close(status: String, message: String? = null) {
        if (message != null) error(message)
        if (closing) return
        if (encoder == null && device == null) {
            closeLatch?.countDown()
            return
        }
        closing = true
        closeStatus = status
        recording = false
        runCatching { session?.stopRepeating() }
        runCatching { session?.close() }
        session = null
        runCatching { device?.close() }
        device = null
        runCatching { previewSink?.close() }
        previewSink = null
        val enc = encoder
        if (enc != null && outputFormat != null && runCatching { enc.signalEndOfInputStream() }.isSuccess) {
            handler.postDelayed({ finishClose() }, 700)
        } else {
            finishClose()
        }
    }

    private fun finishClose() {
        if (!closing) return
        closing = false
        encoder?.let { runCatching { it.stop() }; runCatching { it.release() } }
        encoder = null
        inputSurface?.release()
        inputSurface = null
        closeMuxer()
        outputFormat = null
        log.event("camera", fields = arrayOf("status" to closeStatus))
        closeLatch?.countDown()
        closeLatch = null
    }

    private fun error(message: String) {
        Log.w(TAG, message)
        log.event("camera", fields = arrayOf("status" to "error", "message" to message))
    }

    private fun chooseSize(cam: FrontCameraInfo): Size {
        val target = when (config.resolution) {
            "480p" -> 480
            "1080p" -> 1080
            else -> 720
        }
        val sizes = cam.chars.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            ?.getOutputSizes(MediaCodec::class.java).orEmpty()
        require(sizes.isNotEmpty()) { "front camera offers no video sizes" }
        // Same aspect ratio as the sensor (usually 4:3 on front cameras): the full field of
        // view, and some drivers (the Pixel 3's) lose every frame at a cropped 16:9 size.
        val active = cam.chars.get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE)
        val sensorAspect = active?.let { maxOf(it.width(), it.height()).toDouble() / minOf(it.width(), it.height()) } ?: (4.0 / 3)
        fun aspect(s: Size) = maxOf(s.width, s.height).toDouble() / minOf(s.width, s.height)
        val matching = sizes.filter { abs(aspect(it) - sensorAspect) < 0.02 }.ifEmpty { sizes.toList() }
        // closest short side to the target
        return matching.minWith(compareBy<Size> { abs(minOf(it.width, it.height) - target) }
            .thenBy { abs(aspect(it) - sensorAspect) })
    }

    private fun chooseFps(cam: FrontCameraInfo): Range<Int> {
        val ranges = cam.chars.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES).orEmpty()
        return ranges.filter { it.upper == config.fps }.maxByOrNull { it.lower }
            ?: ranges.filter { it.upper >= config.fps }.minByOrNull { it.upper }
            ?: Range(config.fps, config.fps)
    }
}

/**
 * The front camera for the camera_check step: runs the camera's own face detection
 * on a small, never-displayed stream and reports whether a face is in view.
 */
class FaceCheckCamera(context: Context, private val onFace: (Boolean) -> Unit, private val onUnavailable: () -> Unit) {
    private val manager = context.getSystemService(CameraManager::class.java)
    private val thread = HandlerThread("face-check").apply { start() }
    private val handler = Handler(thread.looper)
    private var device: CameraDevice? = null
    private var reader: ImageReader? = null

    @SuppressLint("MissingPermission")
    @Suppress("DEPRECATION")
    fun start() = handler.post {
        val cam = runCatching { FrontCameraInfo.find(manager) }.getOrNull() ?: return@post onUnavailable()
        val modes = cam.chars.get(CameraCharacteristics.STATISTICS_INFO_AVAILABLE_FACE_DETECT_MODES) ?: intArrayOf()
        val mode = modes.maxOrNull() ?: CaptureRequest.STATISTICS_FACE_DETECT_MODE_OFF
        if (mode == CaptureRequest.STATISTICS_FACE_DETECT_MODE_OFF) return@post onUnavailable()
        val r = ImageReader.newInstance(640, 480, ImageFormat.YUV_420_888, 2).also { reader = it }
        r.setOnImageAvailableListener({ it.acquireLatestImage()?.close() }, handler)
        try {
            manager.openCamera(cam.id, object : CameraDevice.StateCallback() {
                override fun onOpened(d: CameraDevice) {
                    device = d
                    d.createCaptureSession(listOf(r.surface), object : CameraCaptureSession.StateCallback() {
                        override fun onConfigured(s: CameraCaptureSession) {
                            val request = d.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
                                addTarget(r.surface)
                                set(CaptureRequest.STATISTICS_FACE_DETECT_MODE, mode)
                            }.build()
                            s.setRepeatingRequest(request, object : CameraCaptureSession.CaptureCallback() {
                                override fun onCaptureCompleted(s: CameraCaptureSession, q: CaptureRequest, result: TotalCaptureResult) {
                                    onFace(!result.get(CaptureResult.STATISTICS_FACES).isNullOrEmpty())
                                }
                            }, handler)
                        }

                        override fun onConfigureFailed(s: CameraCaptureSession) = onUnavailable()
                    }, handler)
                }

                override fun onDisconnected(d: CameraDevice) = d.close()
                override fun onError(d: CameraDevice, code: Int) {
                    d.close()
                    onUnavailable()
                }
            }, handler)
        } catch (e: Exception) {
            onUnavailable()
        }
    }

    /** Closes the camera; blocks until done (max 1 s) so the recorder can open it next. */
    fun stop() {
        val done = CountDownLatch(1)
        handler.post {
            runCatching { device?.close() }
            device = null
            runCatching { reader?.close() }
            reader = null
            done.countDown()
        }
        done.await(1, TimeUnit.SECONDS)
        thread.quitSafely()
    }
}
