package org.socialeyes.pictogram.neon

import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.sqrt

/** One validation dot: where it was on the screen, and the gaze samples in the window before its tap. */
data class DotGaze(val screenX: Double, val screenY: Double, val gaze: List<GazeSample>, val windowS: Double)

data class CheckResult(
    val dots: Int,
    val followed: Int,
    val rateHz: Double,
    val wornShare: Double,
    val passed: Boolean,
    /** Why it failed, in the researcher's words; empty when it passed. */
    val reasons: List<String>,
    val perDot: List<Boolean>,
)

/**
 * The live check after a validation step (CAM-219), without the scene video: is gaze arriving at
 * Neon's rate, do the glasses say they're worn, and did gaze follow the dots? The last is an affine
 * fit from the dots' screen positions to each dot's median gaze (scene camera pixels): while the
 * phone stays roughly where it is, the dots' layout appears in the scene camera through a near-affine
 * map, so a dot whose gaze lands well off the fit wasn't looked at (or the glasses slipped). It can't
 * say how accurate gaze is in degrees; the full scoring runs afterwards (socialeyes gaze).
 */
object ValidationCheck {
    const val MIN_RATE_HZ = 100.0      // Neon delivers 200 Hz
    const val MIN_WORN = 0.9
    const val FOLLOWED_SHARE = 0.75
    const val MIN_SAMPLES = 3
    private const val RESIDUAL_OF_SPACING = 0.3
    private const val MIN_SCALE = 0.02  // scene px per screen px: frozen gaze collapses the fit
    private const val MAX_SCALE = 5.0

    fun evaluate(dots: List<DotGaze>, sceneStreaming: Boolean? = null): CheckResult {
        val all = dots.flatMap { it.gaze }
        val window = dots.sumOf { it.windowS }
        val rate = if (window > 0) all.size / window else 0.0
        val worn = if (all.isNotEmpty()) all.count { it.worn }.toDouble() / all.size else 0.0
        val perDot = followed(dots)
        val n = perDot.count { it }
        val reasons = buildList {
            if (rate < MIN_RATE_HZ) add("gaze arrived at ${rate.toInt()} samples a second (Neon gives 200): check the glasses' cable and Companion")
            if (all.isNotEmpty() && worn < MIN_WORN) add("the glasses reported not being worn ${((1 - worn) * 100).toInt()}% of the time")
            if (sceneStreaming == false) add("Companion's scene video isn't streaming")
            if (n < maxOf(4, (FOLLOWED_SHARE * dots.size).toInt())) add("gaze followed $n of ${dots.size} dots: the glasses may sit badly or have slipped")
        }
        return CheckResult(dots.size, n, rate, worn, reasons.isEmpty(), reasons, perDot)
    }

    /** Per dot: did its gaze land where the fit through the other dots puts it? */
    fun followed(dots: List<DotGaze>): List<Boolean> {
        val med = dots.map { d ->
            if (d.gaze.size < MIN_SAMPLES) null else Pair(median(d.gaze.map { it.x.toDouble() }), median(d.gaze.map { it.y.toDouble() }))
        }
        val usable = dots.indices.filter { med[it] != null }
        if (usable.size < 4) return dots.map { false }
        var inliers = usable
        var fit: Affine? = null
        var threshold = 0.0
        repeat(usable.size / 3 + 1) {
            val f = Affine.fit(inliers.map { dots[it].screenX to dots[it].screenY }, inliers.map { med[it]!! }) ?: return dots.map { false }
            fit = f
            val predicted = usable.map { f.apply(dots[it].screenX, dots[it].screenY) }
            threshold = RESIDUAL_OF_SPACING * spacing(predicted)
            val resid = inliers.associateWith { i -> f.residual(dots[i].screenX, dots[i].screenY, med[i]!!) }
            val worst = resid.maxByOrNull { it.value } ?: return@repeat
            if (worst.value <= threshold || inliers.size <= 4) return@repeat
            inliers = inliers - worst.key
        }
        val f = fit ?: return dots.map { false }
        if (f.det <= 0 || sqrt(f.det) !in MIN_SCALE..MAX_SCALE) return dots.map { false }   // frozen, or mirrored
        return dots.indices.map { i -> med[i]?.let { f.residual(dots[i].screenX, dots[i].screenY, it) <= threshold } ?: false }
    }

    private fun median(v: List<Double>): Double = v.sorted().let { s -> if (s.size % 2 == 1) s[s.size / 2] else (s[s.size / 2 - 1] + s[s.size / 2]) / 2 }

    /** Median distance from each point to its nearest neighbour. */
    private fun spacing(p: List<Pair<Double, Double>>): Double =
        median(p.mapIndexed { i, a -> p.filterIndexed { j, _ -> j != i }.minOf { b -> hypot(a.first - b.first, a.second - b.second) } })

    /** g = A (s, 1): six parameters, least squares. */
    class Affine(private val a: DoubleArray, private val b: DoubleArray) {
        val det: Double get() = a[0] * b[1] - a[1] * b[0]
        fun apply(x: Double, y: Double) = Pair(a[0] * x + a[1] * y + a[2], b[0] * x + b[1] * y + b[2])
        fun residual(x: Double, y: Double, g: Pair<Double, Double>): Double =
            apply(x, y).let { p -> hypot(p.first - g.first, p.second - g.second) }

        companion object {
            fun fit(src: List<Pair<Double, Double>>, dst: List<Pair<Double, Double>>): Affine? {
                val m = Array(3) { DoubleArray(3) }
                val vx = DoubleArray(3)
                val vy = DoubleArray(3)
                for ((s, d) in src.zip(dst)) {
                    val r = doubleArrayOf(s.first, s.second, 1.0)
                    for (i in 0..2) {
                        for (j in 0..2) m[i][j] += r[i] * r[j]
                        vx[i] += r[i] * d.first
                        vy[i] += r[i] * d.second
                    }
                }
                val a = solve3(m, vx) ?: return null
                val b = solve3(m, vy) ?: return null
                return Affine(a, b)
            }

            private fun solve3(m: Array<DoubleArray>, v: DoubleArray): DoubleArray? {
                fun det(c: Array<DoubleArray>) =
                    c[0][0] * (c[1][1] * c[2][2] - c[1][2] * c[2][1]) - c[0][1] * (c[1][0] * c[2][2] - c[1][2] * c[2][0]) +
                        c[0][2] * (c[1][0] * c[2][1] - c[1][1] * c[2][0])
                val d = det(m)
                if (abs(d) < 1e-9) return null
                return DoubleArray(3) { k -> det(Array(3) { i -> DoubleArray(3) { j -> if (j == k) v[i] else m[i][j] } }) / d }
            }
        }
    }
}
