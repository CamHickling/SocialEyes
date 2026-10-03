package org.socialeyes.pictogram.ui

import android.graphics.BitmapFactory
import android.util.LruCache
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.produceState
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Decodes study images off the main thread, downsampled to about the size they
 * are shown at, and keeps recent ones in memory so scrolling back is instant.
 */
object ImageCache {
    private val cache = object : LruCache<String, ImageBitmap>((Runtime.getRuntime().maxMemory() / 4).toInt()) {
        override fun sizeOf(key: String, value: ImageBitmap) = value.width * value.height * 4
    }

    private fun key(file: File, maxWidth: Int) = "${file.path}@$maxWidth"

    fun peek(file: File, maxWidth: Int): ImageBitmap? = cache.get(key(file, maxWidth))

    suspend fun load(file: File, maxWidth: Int): ImageBitmap? = peek(file, maxWidth) ?: withContext(Dispatchers.IO) {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.path, bounds)
        if (bounds.outWidth <= 0) return@withContext null
        var sample = 1
        while (maxWidth > 0 && bounds.outWidth / (sample * 2) >= maxWidth) sample *= 2
        val bitmap = BitmapFactory.decodeFile(file.path, BitmapFactory.Options().apply { inSampleSize = sample })
            ?: return@withContext null
        bitmap.asImageBitmap().also { cache.put(key(file, maxWidth), it) }
    }
}

/** The decoded image, or null while it loads (or if it can't be read). */
@Composable
fun rememberImage(file: File, maxWidth: Int): State<ImageBitmap?> =
    produceState(ImageCache.peek(file, maxWidth), file, maxWidth) {
        if (value == null) value = ImageCache.load(file, maxWidth)
    }
