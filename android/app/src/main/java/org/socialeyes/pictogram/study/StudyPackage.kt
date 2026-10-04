package org.socialeyes.pictogram.study

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import java.io.File

/**
 * The package written by `socialeyes compile` (docs/STUDY_DESIGN.md, "What compile writes"):
 * study.json, plans/<participant>.json, media/, aois/, tags/.
 *
 * Only the fields the app uses are modelled; unknown fields are ignored so the
 * compiler can add new ones without breaking older app builds.
 */
val StudyJson = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
}

const val SUPPORTED_FORMAT_VERSION = 1

@Serializable
data class StudyManifest(
    val format: String,
    @SerialName("format_version") val formatVersion: Int,
    val study: StudyConfig,
    val accounts: Map<String, Account>,
    val images: Map<String, ImageInfo>,
    @SerialName("sync_code") val syncCode: SyncCode,
    @SerialName("validation_points") val validationPoints: Map<String, List<List<Double>>> = emptyMap(),
    @SerialName("screen_tags") val screenTags: Map<String, String> = emptyMap(),
    val stories: List<StoryItem> = emptyList(),
    val reels: List<ReelItem> = emptyList(),
)

/** A story from stories.csv, as resolved by the compiler (grouped by account, in display order). */
@Serializable
data class StoryItem(
    @SerialName("story_id") val storyId: String,
    @SerialName("account_id") val accountId: String,
    val file: String,
    val width: Int,
    val height: Int,
    @SerialName("duration_s") val durationS: Double = 5.0,
    @SerialName("posted_ago") val postedAgo: String? = null,
)

/** A reel from reels.csv, as resolved by the compiler (in display order). */
@Serializable
data class ReelItem(
    @SerialName("reel_id") val reelId: String,
    @SerialName("account_id") val accountId: String,
    val file: String,
    val width: Int,
    val height: Int,
    @SerialName("duration_s") val durationS: Double = 0.0,
    val caption: String = "",
    @SerialName("like_count") val likeCount: Int = 0,
    val audio: String? = null,
    @SerialName("posted_ago") val postedAgo: String? = null,
)

@Serializable
data class StudyConfig(
    val id: String,
    val title: String = "",
    val version: Int,
    val platform: Platform = Platform(),
    val display: Display = Display(),
    val markers: Markers = Markers(),
    val neon: Neon = Neon(),
    val logging: JsonObject = JsonObject(emptyMap()),
    val labels: Map<String, LabelDef> = emptyMap(),
    val feed: FeedConfig = FeedConfig(),
    val procedure: List<JsonObject>,
)

@Serializable
data class Platform(
    val name: String = "Pictogram",
    val theme: String = "light",
    @SerialName("participant_handle") val participantHandle: String = "you",
)

@Serializable
data class Display(@SerialName("sync_patch") val syncPatch: SyncPatchConfig = SyncPatchConfig())

@Serializable
data class SyncPatchConfig(
    val enabled: Boolean = true,
    @SerialName("size_dp") val sizeDp: Int = 16,
    val corner: String = "top_left",
    val low: Int = 20,
    val high: Int = 44,
    @SerialName("bit_ms") val bitMs: Int = 100,
)

@Serializable
data class Markers(@SerialName("screen_tag_ids") val screenTagIds: List<Int> = listOf(0, 1, 2, 3))

@Serializable
data class Neon(val required: Boolean = false)

@Serializable
data class LabelDef(val text: String, val style: String = "banner")

@Serializable
data class FeedConfig(
    @SerialName("time_limit_s") val timeLimitS: Double? = null,
    @SerialName("done_button_after_s") val doneButtonAfterS: Double? = 60.0,
    @SerialName("allow_likes") val allowLikes: Boolean = true,
    @SerialName("allow_comment_typing") val allowCommentTyping: Boolean = false,
    @SerialName("allow_saves") val allowSaves: Boolean = true,
    @SerialName("allow_shares") val allowShares: Boolean = true,
    @SerialName("allow_comment_likes") val allowCommentLikes: Boolean = true,
)

@Serializable
data class Account(
    val handle: String,
    @SerialName("display_name") val displayName: String? = null,
    val avatar: String,
    val verified: Boolean = false,
)

@Serializable
data class ImageInfo(
    val file: String,
    @SerialName("post_id") val postId: String? = null,
    val version: String? = null,
    val width: Int,
    val height: Int,
)

@Serializable
data class SyncCode(val bits: List<Int>, @SerialName("bit_ms") val bitMs: Int)

@Serializable
data class Plan(
    @SerialName("format_version") val formatVersion: Int,
    @SerialName("study_id") val studyId: String,
    @SerialName("study_version") val studyVersion: Int,
    @SerialName("participant_id") val participantId: String,
    @SerialName("group_key") val groupKey: String = "",
    val list: Int = 0,
    val feed: List<FeedPost>,
    val steps: JsonObject = JsonObject(emptyMap()),
)

@Serializable
data class FeedPost(
    val position: Int,
    @SerialName("post_id") val postId: String,
    val role: String,
    val cell: String? = null,
    @SerialName("account_id") val accountId: String,
    @SerialName("image_id") val imageId: String,
    val label: String? = null,
    val caption: String = "",
    @SerialName("like_count") val likeCount: Int = 0,
    @SerialName("posted_ago") val postedAgo: String? = null,
    val comments: List<Comment> = emptyList(),
)

@Serializable
data class Comment(
    @SerialName("account_id") val accountId: String,
    val text: String,
    @SerialName("like_count") val likeCount: Int = 0,
)

/** One procedure step. Steps differ a lot by type, so they are read from the raw JSON on demand. */
class Step(val raw: JsonObject) {
    val id: String = str("id") ?: error("procedure step without id")
    val type: String = str("type") ?: error("procedure step $id has no type")

    fun str(key: String): String? = (raw[key] as? JsonPrimitive)?.takeIf { it.isString }?.content
    fun double(key: String): Double? = (raw[key] as? JsonPrimitive)?.doubleOrNull
    fun int(key: String): Int? = (raw[key] as? JsonPrimitive)?.intOrNull
}

fun JsonObject.flag(key: String, default: Boolean): Boolean =
    (this[key] as? JsonPrimitive)?.booleanOrNull ?: default

class StudyPackage(val dir: File, val manifest: StudyManifest) {
    val study get() = manifest.study
    val steps: List<Step> = manifest.study.procedure.map(::Step)

    fun file(relative: String): File = File(dir, relative)

    fun participantIds(): List<String> =
        File(dir, "plans").listFiles { f -> f.isFile && f.name.endsWith(".json") }
            ?.map { it.name.removeSuffix(".json") }
            ?.sorted()
            .orEmpty()

    fun loadPlan(participantId: String): Plan {
        val plan = StudyJson.decodeFromString<Plan>(File(dir, "plans/$participantId.json").readText())
        require(plan.studyId == study.id) { "plan $participantId is for study ${plan.studyId}, not ${study.id}" }
        require(plan.studyVersion == study.version) {
            "plan $participantId is for version ${plan.studyVersion} of the study, but study.json is version ${study.version}. Recompile."
        }
        return plan
    }

    /** Features the study asks for that this app version can't do yet. Shown on the setup screen. */
    fun unsupportedFeatures(): List<String> = buildList {
        val logging = study.logging
        if (logging.flag("sensors", false)) add("logging.sensors (motion sensors are not recorded yet)")
        if (logging.flag("screen_recording", false)) add("logging.screen_recording (not recorded yet)")
        val camera = logging["front_camera"] as? JsonObject
        if (camera != null && camera.flag("enabled", false)) add("logging.front_camera (not recorded yet)")
        if (study.neon.required) add("neon.required (Neon control is not built yet; sessions run without it)")
        val supportedSteps = setOf(
            "instructions", "marker_calibration", "validation", "questionnaire", "feed", "image_rating", "recognition",
            "profile_photo", "end",
        )
        steps.filter { it.type !in supportedSteps }.forEach {
            add("step '${it.id}' (${it.type}) is shown as a placeholder")
        }
    }

    companion object {
        fun load(dir: File): StudyPackage {
            val manifest = StudyJson.decodeFromString<StudyManifest>(File(dir, "study.json").readText())
            require(manifest.format == "socialeyes-study") { "study.json is not a SocialEyes study package" }
            require(manifest.formatVersion == SUPPORTED_FORMAT_VERSION) {
                "study.json has format_version ${manifest.formatVersion}; this app reads $SUPPORTED_FORMAT_VERSION"
            }
            return StudyPackage(dir, manifest)
        }

        /** Every sub-folder of [root] holding a study.json, loaded or with the reason it failed. */
        fun findAll(root: File): List<Pair<File, Result<StudyPackage>>> =
            root.listFiles { f -> File(f, "study.json").isFile }
                ?.sortedBy { it.name }
                ?.map { it to runCatching { load(it) } }
                .orEmpty()
    }
}
