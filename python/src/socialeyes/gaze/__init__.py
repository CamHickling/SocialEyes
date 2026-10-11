"""Gaze on the phone screen: where the phone is in each Neon scene frame, and gaze mapped onto it.

    neon      reading a Neon recording in Companion's native format
    tags      AprilTag detection tuned for small on-screen tags
    tracking  the phone's pose per scene frame (PnP on the tags, short gaps bridged by optical flow)
    mapping   gaze samples -> screen pixels
"""
