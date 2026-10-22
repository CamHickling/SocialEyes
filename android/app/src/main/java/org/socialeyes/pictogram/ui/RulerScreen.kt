package org.socialeyes.pictogram.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.socialeyes.pictogram.device.ScreenScale
import org.socialeyes.pictogram.device.ScreenScale.RULER_X_MM
import org.socialeyes.pictogram.device.ScreenScale.RULER_Y_MM

/**
 * Researcher's ruler check (CAM-227): a 50 mm line across and a 100 mm line down, drawn at the dpi
 * the phone reports. The researcher measures both with a ruler; ScreenScale keeps the correction, so
 * the on-screen tags are their true size and gaze lands on the screen in true millimetres.
 */
@Composable
fun RulerScreen(onDone: () -> Unit) {
    val context = LocalContext.current
    val (xdpi, ydpi) = remember { ScreenScale.reported(context) }
    var across by remember { mutableStateOf("") }
    var down by remember { mutableStateOf("") }
    var problem by remember { mutableStateOf<String?>(null) }
    val acrossPx = (RULER_X_MM / 25.4 * xdpi).toFloat()
    val downPx = (RULER_Y_MM / 25.4 * ydpi).toFloat()
    val ink = MaterialTheme.colorScheme.onBackground

    Column(Modifier.fillMaxSize().padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Check screen size", fontSize = 20.sp)
        Text("Measure each line with a ruler, from end mark to end mark, and type the lengths in millimetres. " +
            "Once per phone: SocialEyes then sizes the eye-tracking tags and places gaze in true millimetres.", fontSize = 14.sp)
        Box(Modifier.fillMaxWidth().weight(1f)) {
            Canvas(Modifier.fillMaxSize()) {
                val tick = 14.dp.toPx()
                // across: near the top, starting a little in from the left
                val y = 24.dp.toPx()
                val x0 = 12.dp.toPx()
                drawLine(ink, Offset(x0, y), Offset(x0 + acrossPx, y), strokeWidth = 3f)
                drawLine(ink, Offset(x0, y - tick), Offset(x0, y + tick), strokeWidth = 3f)
                drawLine(ink, Offset(x0 + acrossPx, y - tick), Offset(x0 + acrossPx, y + tick), strokeWidth = 3f)
                // down: along the right of the area, as long as it fits (100 mm fits any phone held upright)
                val x = size.width - 24.dp.toPx()
                val y0 = 56.dp.toPx()
                drawLine(ink, Offset(x, y0), Offset(x, y0 + downPx), strokeWidth = 3f)
                drawLine(ink, Offset(x - tick, y0), Offset(x + tick, y0), strokeWidth = 3f)
                drawLine(ink, Offset(x - tick, y0 + downPx), Offset(x + tick, y0 + downPx), strokeWidth = 3f)
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            OutlinedTextField(across, { across = it; problem = null }, label = { Text("Across (mm)") }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.weight(1f))
            OutlinedTextField(down, { down = it; problem = null }, label = { Text("Down (mm)") }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.weight(1f))
        }
        problem?.let { Text(it, color = Color(0xFFB3261E), fontSize = 14.sp) }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(onClick = {
                val a = across.replace(',', '.').toDoubleOrNull()
                val d = down.replace(',', '.').toDoubleOrNull()
                problem = when {
                    a == null || d == null -> "Type both lengths in millimetres, e.g. 49.5."
                    !ScreenScale.plausible(RULER_X_MM, a) -> "The line across should measure about 50 mm: measure it again."
                    !ScreenScale.plausible(RULER_Y_MM, d) -> "The line down should measure about 100 mm: measure it again."
                    else -> null
                }
                if (problem == null) {
                    ScreenScale.save(context, a!!, d!!)
                    (context as? android.app.Activity)?.let(ScreenScale::writeProfile)
                    onDone()
                }
            }) { Text("Save") }
            TextButton(onClick = onDone) { Text("Cancel") }
        }
    }
}
