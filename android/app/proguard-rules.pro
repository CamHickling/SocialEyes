# R8 rules for the release build (app/build.gradle.kts).
# kotlinx-serialization, Compose, Media3 and CameraX ship their own keep rules.

# Shrink, but keep class and method names so crash stack traces stay readable
# without a mapping file.
-dontobfuscate
