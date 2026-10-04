package org.socialeyes.pictogram.ui

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Matrix
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import org.socialeyes.pictogram.Session
import org.socialeyes.pictogram.study.Step
import kotlin.math.min

/** The participant's profile photo for this session (null: the default avatar). */
val LocalParticipantPhoto = compositionLocalOf<ImageBitmap?> { null }

/** The participant's avatar: their photo if they took one, else the default silhouette. */
@Composable
fun ParticipantAvatar(size: Dp, dark: Boolean, modifier: Modifier = Modifier) {
    val photo = LocalParticipantPhoto.current
    if (photo == null) {
        DefaultAvatar(size, dark, modifier)
    } else {
        Image(photo, null, modifier.size(size).clip(CircleShape), contentScale = ContentScale.Crop)
    }
}

/**
 * profile_photo step: an optional selfie with the front camera, used as the
 * participant's profile picture for the rest of the session. The photo is kept
 * only in memory (Session.profilePhoto) and never written to storage; the log
 * records only `profile_photo` with the result (`taken`, `skipped` or
 * `camera_unavailable`) and the number of retakes.
 */
@Composable
fun ProfilePhotoStep(session: Session, step: Step, onContinue: () -> Unit) {
    val context = LocalContext.current
    val owner = LocalLifecycleOwner.current
    val allowSkip = step.raw["allow_skip"]?.toString() != "false"
    var permitted by remember {
        mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED)
    }
    var unavailable by remember { mutableStateOf(false) }
    var photo by remember { mutableStateOf<ImageBitmap?>(null) }
    var retakes by remember { mutableIntStateOf(0) }
    var capturing by remember { mutableStateOf(false) }
    val capture = remember { ImageCapture.Builder().setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY).build() }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        permitted = granted
        unavailable = !granted
    }
    LaunchedEffect(Unit) { if (!permitted) permission.launch(Manifest.permission.CAMERA) }

    fun finish(result: String) {
        if (result == "taken") session.profilePhoto = photo
        session.log.event("profile_photo", fields = arrayOf("step_id" to step.id, "result" to result, "retakes" to retakes))
        onContinue()
    }

    fun takePhoto() {
        if (capturing) return
        capturing = true
        capture.takePicture(ContextCompat.getMainExecutor(context), object : ImageCapture.OnImageCapturedCallback() {
            override fun onCaptureSuccess(image: ImageProxy) {
                photo = squareSelfie(image).asImageBitmap()
                capturing = false
            }

            override fun onError(exception: ImageCaptureException) {
                unavailable = true
                capturing = false
            }
        })
    }

    Column(
        Modifier.fillMaxSize().padding(horizontal = 32.dp, vertical = 48.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text("Profile photo", fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(12.dp))
        Text(step.str("text").orEmpty(), fontSize = 16.sp, textAlign = TextAlign.Center)
        Spacer(Modifier.height(28.dp))
        Box(
            Modifier.size(260.dp).clip(CircleShape).background(Color(0xFFDBDBDB)),
            contentAlignment = Alignment.Center,
        ) {
            when {
                photo != null -> Image(photo!!, "your photo", Modifier.fillMaxSize(), contentScale = ContentScale.Crop)
                permitted && !unavailable -> CameraPreview(owner, capture) { unavailable = true }
                else -> DefaultAvatar(260.dp)
            }
        }
        Spacer(Modifier.height(28.dp))
        when {
            unavailable -> {
                Text("The camera isn't available, so the default picture will be used.", textAlign = TextAlign.Center,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(16.dp))
                Button(onClick = { finish("camera_unavailable") }) { Text("Continue") }
            }
            photo != null -> Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                OutlinedButton(onClick = { photo = null; retakes++ }) { Text("Retake") }
                Button(onClick = { finish("taken") }) { Text("Use photo") }
            }
            permitted -> Box(
                Modifier
                    .size(72.dp)
                    .border(4.dp, MaterialTheme.colorScheme.onBackground, CircleShape)
                    .padding(6.dp)
                    .background(if (capturing) Color.Gray else MaterialTheme.colorScheme.onBackground, CircleShape)
                    .clickable { takePhoto() },
            )
        }
        if (allowSkip && photo == null && !unavailable) {
            Spacer(Modifier.height(12.dp))
            TextButton(onClick = { finish("skipped") }) { Text("Skip") }
        }
    }
}

@Composable
private fun CameraPreview(owner: LifecycleOwner, capture: ImageCapture, onError: () -> Unit) {
    val context = LocalContext.current
    // TextureView-based mode, so the round clip applies to the preview.
    val view = remember {
        PreviewView(context).apply {
            implementationMode = PreviewView.ImplementationMode.COMPATIBLE
            scaleType = PreviewView.ScaleType.FILL_CENTER
        }
    }
    DisposableEffect(owner) {
        val future = ProcessCameraProvider.getInstance(context)
        var provider: ProcessCameraProvider? = null
        future.addListener({
            try {
                val p = future.get().also { provider = it }
                val preview = Preview.Builder().build().also { it.setSurfaceProvider(view.surfaceProvider) }
                p.unbindAll()
                p.bindToLifecycle(owner, CameraSelector.DEFAULT_FRONT_CAMERA, preview, capture)
            } catch (e: Exception) {
                onError()
            }
        }, ContextCompat.getMainExecutor(context))
        onDispose { provider?.unbindAll() }
    }
    AndroidView({ view }, Modifier.fillMaxSize())
}

/** Upright, mirrored like the preview, centre-cropped to a square, at most 480 px. */
private fun squareSelfie(image: ImageProxy): Bitmap {
    val src = image.toBitmap()
    val rotation = image.imageInfo.rotationDegrees
    image.close()
    val side = min(src.width, src.height)
    val square = Bitmap.createBitmap(src, (src.width - side) / 2, (src.height - side) / 2, side, side)
    val scale = min(1f, 480f / side)
    val m = Matrix().apply {
        postRotate(rotation.toFloat())
        postScale(-scale, scale)
    }
    return Bitmap.createBitmap(square, 0, 0, side, side, m, true)
}
