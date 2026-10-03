package org.socialeyes.pictogram.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.socialeyes.pictogram.Session
import org.socialeyes.pictogram.log.Clocks
import org.socialeyes.pictogram.study.Step
import org.socialeyes.pictogram.study.StudyJson
import kotlin.math.roundToInt
import kotlin.random.Random

/** A questionnaire item, as in study.yaml (`QItem` in schema.py). */
@Serializable
data class QItem(
    val id: String,
    val kind: String,
    val text: String,
    val required: Boolean = true,
    @SerialName("min_label") val minLabel: String? = null,
    @SerialName("max_label") val maxLabel: String? = null,
    val points: Int? = null,
    val labels: List<String>? = null,
    val options: List<String>? = null,
    /** Display text per option; the logged value is the option itself. Not in study.yaml. */
    @kotlinx.serialization.Transient val optionLabels: List<String>? = null,
)

private fun Step.items(): List<QItem> =
    (raw["items"] as? JsonArray).orEmpty().map { StudyJson.decodeFromJsonElement(QItem.serializer(), it) }

/** A trial of an image_rating or recognition step, from the participant's plan. */
private data class Trial(val imageId: String)

private fun Session.trials(step: Step): List<Trial> =
    ((plan.steps[step.id] as? JsonObject)?.get("trials") as? JsonArray).orEmpty().map {
        Trial((it as JsonObject).getValue("image_id").jsonPrimitive.content)
    }

/** Questionnaire step: all items on one page. `randomize` shuffles them per participant. */
@Composable
fun QuestionnaireStep(session: Session, step: Step, onContinue: () -> Unit) {
    val items = remember {
        val all = step.items()
        if (step.raw["randomize"]?.jsonPrimitive?.content == "true") {
            all.shuffled(Random((session.plan.participantId + ":" + step.id).hashCode()))
        } else all
    }
    ItemsPage(session, step.id, step.str("title").orEmpty(), items, trial = null, onDone = onContinue)
}

/** image_rating: one critical image per page (in the plan's order) with the step's items. */
@Composable
fun ImageRatingStep(session: Session, step: Step, onContinue: () -> Unit) {
    val trials = remember { session.trials(step) }
    val items = remember { step.items() }
    TrialSequence(session, step, trials, onContinue) { i, trial, next ->
        ItemsPage(session, step.id, step.str("title").orEmpty(), items, trial = i, onDone = next) {
            TrialImage(session, trial.imageId)
        }
    }
}

/**
 * recognition: old/new judgement per image, optionally with confidence.
 * Responses: item `old_new` (`old` or `new`, compare with the plan's `answer`)
 * and item `confidence` (1-4).
 */
@Composable
fun RecognitionStep(session: Session, step: Step, onContinue: () -> Unit) {
    val trials = remember { session.trials(step) }
    val items = remember {
        buildList {
            add(
                QItem(
                    id = "old_new", kind = "choice",
                    text = step.str("question") ?: "Did you see exactly this image in the feed?",
                    options = listOf("old", "new"), optionLabels = listOf("Yes", "No"),
                )
            )
            if (step.raw["confidence"]?.jsonPrimitive?.content != "false") {
                add(QItem(id = "confidence", kind = "likert", text = "How sure are you?", points = 4,
                    minLabel = "Guessing", maxLabel = "Certain"))
            }
        }
    }
    TrialSequence(session, step, trials, onContinue) { i, trial, next ->
        ItemsPage(session, step.id, "", items, trial = i, onDone = next) { TrialImage(session, trial.imageId) }
    }
}

@Composable
private fun TrialSequence(
    session: Session,
    step: Step,
    trials: List<Trial>,
    onContinue: () -> Unit,
    page: @Composable (index: Int, trial: Trial, next: () -> Unit) -> Unit,
) {
    var index by remember { mutableIntStateOf(0) }
    if (index >= trials.size) {
        LaunchedEffect(Unit) { onContinue() }
        return
    }
    val trial = trials[index]
    LaunchedEffect(index) {
        session.log.event("trial_start", fields = arrayOf("step_id" to step.id, "trial" to index, "image_id" to trial.imageId))
    }
    androidx.compose.runtime.key(index) {
        page(index, trial) { index++ }
    }
}

@Composable
private fun TrialImage(session: Session, imageId: String) {
    val info = session.pkg.manifest.images.getValue(imageId)
    val maxWidth = with(LocalDensity.current) { LocalConfiguration.current.screenWidthDp.dp.roundToPx() }
    val bitmap by rememberImage(session.pkg.file(info.file), maxWidth)
    val maxHeight = (LocalConfiguration.current.screenHeightDp * 0.45f).dp
    Box(Modifier.fillMaxWidth().heightIn(max = maxHeight), contentAlignment = Alignment.Center) {
        Box(
            Modifier
                .aspectRatio(info.width.toFloat() / info.height, matchHeightConstraintsFirst = true)
                .background(MaterialTheme.colorScheme.surfaceVariant),
        ) {
            bitmap?.let { Image(it, null, Modifier.fillMaxSize(), contentScale = ContentScale.FillBounds) }
        }
    }
}

/**
 * Items on one page with a Continue button that unlocks when every required
 * item is answered. Logs `items_shown`, `response_change` for every change
 * (except typing) and, on Continue, one `response` per answered item, with
 * `rt_ms` = time from the page appearing to the item's last change.
 */
@Composable
private fun ItemsPage(
    session: Session,
    stepId: String,
    title: String,
    items: List<QItem>,
    trial: Int?,
    onDone: () -> Unit,
    header: @Composable () -> Unit = {},
) {
    val log = session.log
    val shownNs = remember { Clocks.elapsedNs() }
    val values = remember { mutableStateMapOf<String, Any>() }
    val changedNs = remember { HashMap<String, Long>() }
    val trialField = if (trial != null) arrayOf<Pair<String, Any?>>("trial" to trial) else emptyArray()

    LaunchedEffect(Unit) {
        log.event("items_shown", fields = arrayOf("step_id" to stepId, "item_ids" to items.map { it.id }, *trialField))
    }

    fun set(item: QItem, value: Any?, logChange: Boolean = true) {
        if (value == null) values.remove(item.id) else values[item.id] = value
        changedNs[item.id] = Clocks.elapsedNs()
        if (logChange && value != null) {
            log.event("response_change", fields = arrayOf("step_id" to stepId, "item_id" to item.id, "value" to value, *trialField))
        }
    }

    val complete = items.all { !it.required || values.containsKey(it.id) }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp, vertical = 32.dp),
        verticalArrangement = Arrangement.spacedBy(28.dp),
    ) {
        if (title.isNotBlank()) Text(title, fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
        header()
        for (item in items) {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(item.text, fontSize = 17.sp)
                when (item.kind) {
                    "vas" -> Vas(item, values[item.id] as Double?) { v, final -> set(item, v, logChange = final) }
                    "likert" -> Likert(item, values[item.id] as Int?) { set(item, it) }
                    "choice" -> Choice(item, values[item.id] as String?) { set(item, it) }
                    "number" -> {
                        var text by remember { mutableStateOf("") }
                        OutlinedTextField(
                            text,
                            onValueChange = { t ->
                                text = t
                                val n: Number? = t.trim().toLongOrNull() ?: t.trim().replace(',', '.').toDoubleOrNull()
                                set(item, n, logChange = false)
                            },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                            singleLine = true,
                        )
                    }
                    else -> {
                        var text by remember { mutableStateOf("") }
                        OutlinedTextField(
                            text,
                            onValueChange = { t -> text = t; set(item, t.trim().ifEmpty { null }, logChange = false) },
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                }
            }
        }
        Button(
            onClick = {
                for (item in items) {
                    val v = values[item.id] ?: continue
                    val rt = ((changedNs[item.id] ?: shownNs) - shownNs) / 1_000_000
                    log.event("response", fields = arrayOf("step_id" to stepId, "item_id" to item.id, "value" to v, "rt_ms" to rt, *trialField))
                }
                onDone()
            },
            enabled = complete,
            modifier = Modifier.align(Alignment.CenterHorizontally),
        ) { Text("Continue") }
    }
}

/**
 * Visual analogue scale: a line with no marker until the participant taps or
 * drags. Value 0-1 (3 decimals). Changes are logged when the finger lifts.
 */
@Composable
private fun Vas(item: QItem, value: Double?, onChange: (Double, final: Boolean) -> Unit) {
    val color = MaterialTheme.colorScheme.onSurface
    val accent = MaterialTheme.colorScheme.primary
    Column {
        BoxWithConstraints(Modifier.fillMaxWidth().height(48.dp)) {
            val widthPx = constraints.maxWidth.toFloat()
            val pad = with(LocalDensity.current) { 12.dp.toPx() }
            fun toValue(x: Float) = (((x - pad) / (widthPx - 2 * pad)).coerceIn(0f, 1f) * 1000).roundToInt() / 1000.0
            var dragValue by remember { mutableStateOf<Double?>(null) }
            Canvas(
                Modifier
                    .fillMaxSize()
                    .pointerInput(Unit) { detectTapGestures { onChange(toValue(it.x), true) } }
                    .pointerInput(Unit) {
                        detectHorizontalDragGestures(
                            onDragStart = { dragValue = toValue(it.x); onChange(dragValue!!, false) },
                            onDragEnd = { dragValue?.let { onChange(it, true) }; dragValue = null },
                            onDragCancel = { dragValue?.let { onChange(it, true) }; dragValue = null },
                        ) { change, _ -> dragValue = toValue(change.position.x); onChange(dragValue!!, false) }
                    },
            ) {
                val y = size.height / 2
                drawLine(color, Offset(pad, y), Offset(size.width - pad, y), strokeWidth = 3.dp.toPx())
                drawLine(color, Offset(pad, y - 10.dp.toPx()), Offset(pad, y + 10.dp.toPx()), strokeWidth = 3.dp.toPx())
                drawLine(color, Offset(size.width - pad, y - 10.dp.toPx()), Offset(size.width - pad, y + 10.dp.toPx()), strokeWidth = 3.dp.toPx())
                value?.let {
                    val x = pad + it.toFloat() * (size.width - 2 * pad)
                    drawLine(accent, Offset(x, y - 16.dp.toPx()), Offset(x, y + 16.dp.toPx()), strokeWidth = 4.dp.toPx())
                }
            }
        }
        Row(Modifier.fillMaxWidth()) {
            Text(item.minLabel.orEmpty(), fontSize = 13.sp, modifier = Modifier.weight(1f))
            Text(item.maxLabel.orEmpty(), fontSize = 13.sp, textAlign = TextAlign.End, modifier = Modifier.weight(1f))
        }
    }
}

/** Likert scale: numbered circles 1..points, with per-point labels or end labels. */
@Composable
private fun Likert(item: QItem, value: Int?, onChange: (Int) -> Unit) {
    val points = item.points ?: 7
    Column {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            for (p in 1..points) {
                Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
                    val selected = value == p
                    Box(
                        Modifier
                            .size(40.dp)
                            .border(2.dp, MaterialTheme.colorScheme.onSurface, CircleShape)
                            .background(if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surface, CircleShape)
                            .clickable { onChange(p) },
                        contentAlignment = Alignment.Center,
                    ) {
                        Text("$p", color = if (selected) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface)
                    }
                    item.labels?.getOrNull(p - 1)?.let {
                        Spacer(Modifier.height(4.dp))
                        Text(it, fontSize = 11.sp, textAlign = TextAlign.Center)
                    }
                }
            }
        }
        if (item.labels == null && (item.minLabel != null || item.maxLabel != null)) {
            Row(Modifier.fillMaxWidth().padding(top = 4.dp)) {
                Text(item.minLabel.orEmpty(), fontSize = 13.sp, modifier = Modifier.weight(1f))
                Text(item.maxLabel.orEmpty(), fontSize = 13.sp, textAlign = TextAlign.End, modifier = Modifier.weight(1f))
            }
        }
    }
}

@Composable
private fun Choice(item: QItem, value: String?, onChange: (String) -> Unit) {
    val options = item.options.orEmpty()
    Column {
        options.forEachIndexed { i, option ->
            Row(
                Modifier.fillMaxWidth().clickable { onChange(option) }.padding(vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                RadioButton(selected = value == option, onClick = { onChange(option) })
                Text(item.optionLabels?.getOrNull(i) ?: option, fontSize = 16.sp)
            }
        }
    }
}
