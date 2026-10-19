"""The ``socialeyes`` command-line tool.

    socialeyes validate STUDY_DIR
    socialeyes compile STUDY_DIR [-o OUT] [--clean]
    socialeyes case-sheet --width-mm W --height-mm H [--study STUDY_DIR] [-o case_sheet.svg]
    socialeyes session SESSION_DIR [--build BUILD_DIR] [-o OUT]
    socialeyes gaze NEON_DIR SESSION_DIR [-o OUT] [--max-bridge-ms MS]
    socialeyes calibrate-display PHONE_IP [--check] [--brightness ...] [--exposures ...] [-o OUT]
    socialeyes simulate BUILD_DIR PARTICIPANT_ID OUT_DIR [--seed N]
    socialeyes phone-check [STUDY_DIR] [--serial S]
    socialeyes load STUDY_DIR [--serial S] [--update-app] [--anyway]
    socialeyes unload STUDY_DIR [--serial S]
    socialeyes folders STUDY_DIR [--data DIR] [--second-copy DIR|none]
    socialeyes app [--debug]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__


def _print_report(rep) -> None:
    for w in rep.warnings:
        print(f"warning: {w}", file=sys.stderr)
    for e in rep.errors:
        print(f"error: {e}", file=sys.stderr)


def cmd_validate(args) -> int:
    from .study.compiler import check_study
    from .study.design import cells

    b, rep = check_study(args.study)
    _print_report(rep)
    if b is None:
        print(f"{len(rep.errors)} error(s); the study cannot be compiled.", file=sys.stderr)
        return 1
    s = b.study
    print(f"OK: {s.id} v{s.version}")
    print(f"  posts: {len(b.critical)} critical, {len(b.fillers)} filler")
    print(f"  within cells ({len(cells(s.within))}): {', '.join(c.key for c in cells(s.within))}")
    print(f"  between groups ({len(cells(s.between))}): {', '.join(g.key for g in cells(s.between))}")
    print(f"  balanced block size: {len(cells(s.within)) * len(cells(s.between))} participants")
    return 0


def cmd_compile(args) -> int:
    from .study.compiler import StudyError, compile_study

    try:
        out, rep = compile_study(args.study, args.out, clean=args.clean)
    except StudyError as e:
        for w in e.warnings:
            print(f"warning: {w}", file=sys.stderr)
        for err in e.errors:
            print(f"error: {err}", file=sys.stderr)
        print(f"{len(e.errors)} error(s); nothing was written.", file=sys.stderr)
        return 1
    except FileExistsError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    _print_report(rep)
    n = len(list((out / "plans").glob("*.json")))
    print(f"Wrote {out} ({n} participant plans)")
    return 0


def cmd_case_sheet(args) -> int:
    from .markers import case_sheet_svg

    tag_ids, size = args.tag_ids, args.tag_size_mm
    if args.study:
        from .study.compiler import load_study_yaml, Report

        path = Path(args.study)
        rep = Report()
        study = load_study_yaml(path if path.suffix.lower() in (".yaml", ".yml") else path / "study.yaml", rep)
        if study is None:
            _print_report(rep)
            return 1
        tag_ids = tag_ids or study.markers.case_tag_ids
        size = size or study.markers.case_tag_size_mm
    svg, layout = case_sheet_svg(args.width_mm, args.height_mm, tag_ids or [10, 11, 12, 13, 14, 15], size or 15.0)
    out = Path(args.out)
    out.write_text(svg, encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(layout, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out} and {out.with_suffix('.json').name}. Print at 100% scale and check that one tag "
          f"measures {layout['tag_size_mm']} mm.")
    return 0


def cmd_session(args) -> int:
    from .session.analyze import analyze_session, default_out_dir, write_results
    from .session.io import SessionFormatError

    try:
        results = analyze_session(args.session, args.build, finger_radius_mm=args.finger_radius_mm)
    except (SessionFormatError, ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    q = results["quality"]
    out = Path(args.out) if args.out else default_out_dir(args.session, q, _study_id(args.session))
    write_results(results, out)
    for w in q["warnings"]:
        print(f"warning: {w}", file=sys.stderr)
    status = "completed" if q["completed"] else f"NOT completed ({q['end_reason']})"
    print(f"{q['participant_id']}: {status}, {q['duration_s']:.0f} s (feed {q['feed_duration_s']:.0f} s)")
    gestures = results["strokes"]["gesture"].value_counts().to_dict()
    print(f"  gestures: {gestures}")
    if not args.build:
        print("  (no --build given: touches are not mapped to images/AOIs)")
    print(f"Wrote {out}")
    return 0


def cmd_face(args) -> int:
    from .face.analyze import analyze_faces, write_face
    from .session.analyze import default_out_dir
    from .session.io import SessionFormatError

    def progress(n, total):
        if n % 500 == 0:
            print(f"  frame {n} of {total}", flush=True)

    try:
        r = analyze_faces(args.session, progress=progress)
    except (SessionFormatError, ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else default_out_dir(args.session, r.summary, _study_id(args.session))
    write_face(r, out)
    for step, st in r.summary["steps"].items():
        looking = "" if st["looking_share"] is None else f", looking at the phone {100 * st['looking_share']:.0f}%"
        dist = "" if st["distance_mm_median"] is None else f", {st['distance_mm_median'] / 10:.0f} cm away"
        print(f"  {step}: face in {100 * st['face_share']:.0f}% of {st['frames']} frames{looking}{dist}")
    for w in r.summary["warnings"]:
        print(f"warning: {w}", file=sys.stderr)
    if args.blur:
        from .face.blur import blur_session

        files = blur_session(args.session, r.frames, out / "camera_blurred", progress=progress)
        print(f"  blurred copies: {len(files)} file(s) in {out / 'camera_blurred'}")
    print(f"Wrote {out}")
    return 0


def cmd_aois(args) -> int:
    from . import settings
    from .face.body_aois import study_aois
    from .phone.unload import study_id_of

    try:
        review = settings.analysis_dir(study_id_of(args.study)) / "aoi_review"
        r = study_aois(args.study, all_images=args.all, overwrite=args.overwrite, review_dir=review,
                       progress=lambda s: print(s, flush=True))
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for img, aoi in r.written:
        print(f"  wrote {aoi}")
    if r.kept:
        print(f"  kept {len(r.kept)} existing AOI file(s) (--overwrite replaces them)")
    for img, why in r.empty:
        print(f"  no AOIs for {img}: {why}")
    for res in r.images:
        for n in res.notes:
            if res.aois:
                print(f"  check {res.image}: {n}")
    print(f"Review them: {r.review}")
    return 0


def cmd_gaze(args) -> int:
    from .gaze.mapping import map_gaze, summary
    from .gaze.neon import NeonFormatError, read_recording
    from .gaze.tracking import clock_offset_ns, track_recording
    from .session.io import SessionFormatError, load_session

    try:
        rec = read_recording(args.neon)
        session = load_session(args.session)
        progress = lambda step, n, total: print(f"  {step}: frame {n}/{total}", file=sys.stderr, flush=True)  # noqa: E731
        tracking = track_recording(rec, session, args.max_bridge_ms, progress)
    except (NeonFormatError, SessionFormatError, ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    dev = session.device
    gaze = map_gaze(rec, tracking, clock_offset_ns(session), dev["screen_width_px"], dev["screen_height_px"])
    out = Path(args.out) if args.out else (Path("analysis_out") / (_study_id(args.session) or "unknown")
                                           / session.participant_id / (session.meta.get("session_uid") or Path(args.session).name))
    out.mkdir(parents=True, exist_ok=True)
    tracking.to_csv(out / "screen_tracking.csv", index=False)
    gaze.to_csv(out / "gaze_screen.csv", index=False)
    print(f"{session.participant_id}: phone tracked in {len(tracking)} scene frames")
    print(summary(tracking, gaze).to_string(index=False))
    print(f"Wrote {out / 'screen_tracking.csv'} and {out / 'gaze_screen.csv'}")

    # Neon's fixations, on the screen and on the post images (with the build the session ran)
    from .gaze.fixations import map_fixations, read_fixations

    build = Path(args.build) if args.build else None
    if build is None and session.package_sha256 and _study_id(args.session):
        from . import settings

        snap = settings.build_snapshot(_study_id(args.session), session.package_sha256)
        build = snap if (snap / "study.json").is_file() else None
    try:
        fix = map_fixations(read_fixations(args.neon), gaze, session, clock_offset_ns(session), build)
    except FileNotFoundError as e:
        print(f"warning: no fixations: {e}", file=sys.stderr)
        return 0
    fix.to_csv(out / "fixations.csv", index=False)
    on_img = fix[fix["image_id"].fillna("") != ""]
    print(f"{len(fix)} fixations, {len(on_img)} on post images" + ("" if build else
          " (no build found: give --build to place them on the images)"))
    print(f"Wrote {out / 'fixations.csv'}")
    return 0


def cmd_heatmaps(args) -> int:
    from .gaze.heatmap import study_heatmaps

    try:
        r, skipped = study_heatmaps(args.study, data_dir=args.data, out_dir=args.out, by=args.by,
                                    sigma_deg=args.sigma_deg, progress=lambda s: print(s, flush=True))
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for folder, why in skipped:
        print(f"  skipped {folder}: {why}")
    print(f"{len(r.images)} image(s) with fixations")
    print(f"Wrote {r.page}")
    return 0


def cmd_calibrate_display(args) -> int:
    import time
    import urllib.error

    from .gaze import display_calibration as dc

    app = dc.AppLink(args.phone, args.app_port)
    print(f"Waiting for the app's display calibration step at {args.phone}:{args.app_port} "
          f"(start the session on the phone)...", flush=True)
    deadline = time.monotonic() + args.wait_s
    while True:
        try:
            state = app.state()
            break
        except (urllib.error.URLError, OSError, TimeoutError):
            if time.monotonic() > deadline:
                print("error: the app didn't answer. Is the session at its display calibration step, and are the "
                      "phone and this laptop on the same network?", file=sys.stderr)
                return 1
            time.sleep(2)
    print(f"Connected: session {state.get('session_uid')}, step {state.get('step_id')}; "
          f"phone brightness {state.get('system_brightness')}, scene camera {state.get('camera')}")
    try:
        scene = dc.NeonScene(args.phone, args.neon_port)
    except Exception as e:  # the real-time API raises its own errors for an unreachable Companion
        print(f"error: can't reach Neon Companion's real-time API at {args.phone}:{args.neon_port}: {e}", file=sys.stderr)
        return 1
    try:
        K = dist = None
        if not (state.get("calibration") or {}).get("K"):
            K, dist = scene.calibration()
        layout = dc.Layout.from_state(state, K, dist)
        if args.check:
            t = app.apply(None, {})  # changes nothing; answers with the phone's time
            frames = scene.frames_after(t, 5, timeout_s=10)
            m, _ = dc.measure(frames, layout, dc.TagDetector(), state.get("brightness") or 1.0, {})
            print(f"Check: {len(frames)} scene frames; tags read {m.tags_read:.0%}, blown out "
                  f"{'-' if m.blown_out is None else f'{m.blown_out:.0%}'}. Nothing was changed.")
            return 0 if frames else 1
        levels = [float(x) for x in args.brightness.split(",")]
        exposures = [x if x == "auto" else int(x) for x in args.exposures.split(",")]
        plan = dc.settings(state, levels, exposures, args.min_brightness)
        target = args.target_brightness if args.target_brightness is not None else state.get("system_brightness")
        print(f"Trying {len(plan)} settings (about {len(plan) * 0.8 + 6:.0f} s); "
              f"the participant should keep looking at the screen.")
        best, measures = dc.calibrate(app, scene, layout, plan, frames=args.frames, target_brightness=target)
        result = dc.summary(best, measures)
        if best is None:
            print("No setting let the scene camera read the tags. Is the phone in view of the glasses? "
                  "The app keeps its previous settings.")
            app.done(None, None, result)
        else:
            print(f"Best: {best.label} (tags read {best.tags_read:.0%}, blown out "
                  f"{'-' if best.blown_out is None else f'{best.blown_out:.0%}'}); sent to the app.")
            app.done(best.brightness, best.camera, result)
        out = Path(args.out) if args.out else Path("analysis_out") / "display_calibration" / f"{state.get('session_uid', 'session')}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"state": state, **result}, indent=1), encoding="utf-8")
        print(f"Wrote {out}")
        return 0 if best else 1
    finally:
        scene.close()


def _study_id(session_dir) -> str | None:
    try:
        return json.loads((Path(session_dir) / "session.json").read_text(encoding="utf-8")).get("study_id")
    except (OSError, ValueError):
        return None


def cmd_simulate(args) -> int:
    from .session.simulate import simulate_session

    out = simulate_session(args.build, args.participant, args.out, seed=args.seed)
    print(f"Wrote simulated session to {out}")
    return 0


_MARK = {"block": "BLOCK", "warn": "WARN ", "info": "  -> ", "ok": "  ok "}


def _print_phone(r) -> None:
    if r.phone:
        p = r.phone
        print(f"Phone: {p.model or p.serial} (Android {p.android}, {p.serial})")
    for c in r.checks:
        print(f"  {_MARK[c.level]} {c.text}")


def cmd_phone_check(args) -> int:
    from .phone.loader import blocked, phone_check

    r = phone_check(args.study, serial=args.serial)
    if r.error:
        print(f"error: {r.error}", file=sys.stderr)
        return 1
    _print_phone(r)
    if blocked(r.checks):
        print("Not ready: fix the BLOCK items first.")
        return 1
    print("Ready" + (" (see the warnings)." if r.needs_confirmation else "."))
    return 0


def cmd_load(args) -> int:
    from .phone.loader import load

    r = load(args.study, serial=args.serial, update_app=args.update_app, anyway=args.anyway,
             progress=lambda s: print(s, flush=True))
    if r.error:
        print(f"error: {r.error}", file=sys.stderr)
        return 1
    if not r.loaded:
        _print_phone(r)
        if r.needs_confirmation:
            print("Not loaded because of the warnings above; add --anyway to load regardless.")
            return 2
        print("Not loaded: fix the BLOCK items first.")
        return 1
    if r.update_available and not args.update_app:
        print("A newer SocialEyes app is available: add --update-app to install it (keeps the phone's data).")
    print(f"Loaded {r.study_id} onto the phone.")
    return 0


def cmd_unload(args) -> int:
    from .phone.unload import clear_phone, unload

    r = (clear_phone if args.clear else unload)(args.study, serial=args.serial, progress=lambda s: print(s, flush=True))
    if r.error:
        print(f"error: {r.error}", file=sys.stderr)
        return 1
    if not r.sessions:
        print(f"No sessions of {r.study_id} on the phone.")
        return 0
    failed = 0
    for s in r.sessions:
        if s.error:
            failed += 1
            print(f"  {s.participant_id} {s.session_uid}: NOT unloaded: {s.error}")
            continue
        state = "deleted from the phone" if s.deleted else f"on the phone: {s.kept_reason}"
        extra = ", second copy checked" if s.second_copy else ""
        done = "" if s.completed is None else (" completed" if s.completed else " NOT completed")
        what = "copied and checked" if s.copied else "not copied"
        print(f"  {s.participant_id} {s.session_uid}:{done}, {what}{extra}, {state}")
        for w in s.warnings:
            print(f"      warning: {w}")
    print(f"Data folder: {r.data_dir} (register: sessions.csv)")
    return 1 if failed else 0


def cmd_export(args) -> int:
    from .session.export import export

    try:
        r = export(args.study, data_dir=args.data, out_dir=args.out, progress=lambda s: print(s, flush=True),
                   faces=not args.no_faces, unblind=args.unblind)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for folder, why in r.skipped:
        print(f"  skipped {folder}: {why}")
    print(f"{r.sessions} session(s) -> {r.out_dir}")
    print(f"  exploration.html ({'UNBLINDED: real condition names' if r.unblinded else 'blinded: conditions as codes'})")
    for f in r.files:
        if not f.endswith("exploration.html"):
            print(f"  {Path(f).name}")
    return 1 if r.skipped and not r.sessions else 0


def _confirm(prompt: str, expected: str, yes: bool) -> bool:
    if yes:
        return True
    try:
        return input(f"{prompt} Type {expected} to confirm: ").strip() == expected
    except EOFError:
        return False


def cmd_withdraw(args) -> int:
    from .session import withdraw as W

    pid = args.participant
    try:
        if args.restore:
            r = W.restore(args.study, pid)
        elif args.delete:
            if not _confirm(f"Delete {pid}'s withdrawn data permanently (this computer and, if connected, the "
                            "phone)? This can't be undone.", pid, args.yes):
                print("Nothing deleted.")
                return 1
            r = W.delete_permanently(args.study, pid, serial=args.serial)
        else:
            if not _confirm(f"Withdraw {pid}? Their data moves to withdrawn/ and leaves the exports (undo with "
                            "--restore).", pid, args.yes):
                print("Nothing changed.")
                return 1
            r = W.withdraw(args.study, pid, reason=args.reason or "")
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"{pid}: {r.action}; {len(r.sessions)} session(s)")
    for a, b in r.moved:
        print(f"  moved {a} -> {b}")
    for d in r.deleted:
        print(f"  deleted {d}")
    for n in r.notes:
        print(f"  note: {n}")
    return 0


def cmd_retention(args) -> int:
    from .session import retention as R

    try:
        d = R.due(args.study)
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for st in R.storage(args.study):
        enc = {True: "on an encrypted drive", False: "NOT on an encrypted drive", None: "drive encryption unknown"}[st["encrypted"]]
        cloud = f"; inside {st['cloud']}, so it uploads itself" if st["cloud"] else ""
        print(f"{st['folder']}: {st['path']} ({enc}{cloud})")
    if not d["keep_until"] and d["face_video_days"] is None:
        print("No retention rules (data: keep_until / face_video_days in study.yaml).")
    else:
        print(f"Keep until: {d['keep_until'] or '-'}; face videos: "
              f"{str(d['face_video_days']) + ' days after unloading' if d['face_video_days'] is not None else '-'}")
        print(f"Due: {len(d['sessions'])} session(s) past keep_until, face videos of {len(d['face_videos'])} session(s)")
    if args.delete:
        what = {"face-videos": "face_videos", "sessions": "sessions"}[args.delete]
        n = len(d[what])
        if not n:
            print("Nothing due.")
            return 0
        if not _confirm(f"Delete {'the face videos of ' if what == 'face_videos' else ''}{n} session(s) from this "
                        "computer? This can't be undone.", "delete", args.yes):
            print("Nothing deleted.")
            return 1
        r = R.delete_due(args.study, what)
        print(f"Deleted {r['files']} file(s) of {len(r['deleted'])} session(s).")
    return 0


def cmd_folders(args) -> int:
    from . import settings
    from .phone.unload import study_id_of

    sid = study_id_of(args.study)
    changes = {}
    if args.data:
        changes["data_dir"] = str(Path(args.data).resolve())
    if args.second_copy:
        changes["second_copy_dir"] = None if args.second_copy.lower() == "none" else str(Path(args.second_copy).resolve())
    if args.clear_after_unload:
        changes["clear_after_unload"] = True if args.clear_after_unload == "on" else None
    if changes:
        settings.set_study(sid, **changes)
    second = settings.second_copy_dir(sid)
    print(f"{sid}: data folder {settings.data_dir(sid)}")
    print(f"{sid}: second copy {second if second else '(none)'}")
    print(f"{sid}: sessions leave the phone "
          f"{'as soon as they are unloaded' if settings.study(sid).get('clear_after_unload') else 'only with: socialeyes unload --clear'}")
    print(f"(saved in {settings.settings_path()})")
    return 0


def cmd_app(args) -> int:
    try:
        import webview  # noqa: F401
    except ImportError:
        print('error: the desktop app needs pywebview: pip install -e "./python[desktop]"', file=sys.stderr)
        return 1
    from .desktop.app import run

    try:
        run(debug=args.debug)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="socialeyes", description="SocialEyes study tools")
    p.add_argument("--version", action="version", version=f"socialeyes {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    v = sub.add_parser("validate", help="check a study folder and report every problem")
    v.add_argument("study", help="study folder (or its study.yaml)")
    v.set_defaults(func=cmd_validate)

    c = sub.add_parser("compile", help="build the package the phone app loads")
    c.add_argument("study", help="study folder (or its study.yaml)")
    c.add_argument("-o", "--out", help="output folder (default: build/<study id>)")
    c.add_argument("--clean", action="store_true", help="replace an existing build in the output folder")
    c.set_defaults(func=cmd_compile)

    k = sub.add_parser("case-sheet", help="printable AprilTag frame for the phone (1:1 SVG)")
    k.add_argument("--width-mm", type=float, required=True, help="phone screen width in mm")
    k.add_argument("--height-mm", type=float, required=True, help="phone screen height in mm")
    k.add_argument("--study", help="take tag ids and size from this study's markers: section")
    k.add_argument("--tag-ids", type=int, nargs="+", help="case tag ids (default 10-15)")
    k.add_argument("--tag-size-mm", type=float, help="tag edge length in mm (default 15)")
    k.add_argument("-o", "--out", default="case_sheet.svg")
    k.set_defaults(func=cmd_case_sheet)

    s = sub.add_parser("session", help="analyse one recorded session (touches, exposure, quality)")
    s.add_argument("session", help="session folder written by the app")
    s.add_argument("--build", help="compiled study folder: maps touches to images and AOIs")
    s.add_argument("-o", "--out", help="output folder (default: analysis_out/<study>/<participant>/<session>)")
    s.add_argument("--finger-radius-mm", type=float, default=8.0,
                   help="AOIs this close to a touch count as covered by the finger (default 8)")
    s.set_defaults(func=cmd_session)

    fc = sub.add_parser("face", help="analyse the front camera video: face present, head pose, distance, looking away")
    fc.add_argument("session", help="session folder (with camera/front_*.mp4)")
    fc.add_argument("-o", "--out", help="output folder (default: analysis_out/<study>/<participant>/<session>)")
    fc.add_argument("--blur", action="store_true", help="also write copies of the video with the face blurred")
    fc.set_defaults(func=cmd_face)

    ao = sub.add_parser("aois", help="draw face and body AOIs on the study's post images automatically")
    ao.add_argument("study", help="study folder (or its study.yaml)")
    ao.add_argument("--all", action="store_true", help="every image in images.csv, not only the critical posts'")
    ao.add_argument("--overwrite", action="store_true", help="replace AOI files that exist already")
    ao.set_defaults(func=cmd_aois)

    g = sub.add_parser("gaze", help="track the phone in a Neon recording and map gaze onto the screen")
    g.add_argument("neon", help="Neon recording folder (native format, copied off the phone)")
    g.add_argument("session", help="the matching session folder written by the app")
    g.add_argument("-o", "--out", help="output folder (default: analysis_out/<study>/<participant>/<session>)")
    g.add_argument("--build", help="the compiled study the session ran, to place fixations on the images "
                                   "(default: the copy kept when it was loaded)")
    g.add_argument("--max-bridge-ms", type=float, default=300.0,
                   help="longest stretch without readable tags bridged by optical flow (default 300)")
    g.set_defaults(func=cmd_gaze)

    hm = sub.add_parser("heatmaps", help="fixation heatmaps over the post images, pooled by condition")
    hm.add_argument("study", help="study folder (or its study.yaml)")
    hm.add_argument("--by", default="cell", help="pool by the within-subjects cell (default) or one factor's levels, e.g. label")
    hm.add_argument("--sigma-deg", type=float, default=1.0, help="each fixation's spread, degrees of visual angle (default 1)")
    hm.add_argument("--data", help="the sessions' folder (default: the study's data folder)")
    hm.add_argument("-o", "--out", help="output folder (default: analysis_out/<study>/heatmaps)")
    hm.set_defaults(func=cmd_heatmaps)

    d = sub.add_parser("calibrate-display", help="during a display_calibration step: find the screen brightness and "
                                                 "Neon scene exposure at which the tags read best")
    d.add_argument("phone", help="the phone's IP address (Companion's, as shown in the Neon Companion app)")
    d.add_argument("--app-port", type=int, default=8091, help="the step's port (default 8091)")
    d.add_argument("--neon-port", type=int, default=8080, help="Companion's real-time API port (default 8080)")
    d.add_argument("--check", action="store_true", help="only check both connections and read a few frames")
    d.add_argument("--brightness", default="1.0,0.75,0.55,0.4,0.3", help="screen brightness levels to try (0-1)")
    d.add_argument("--exposures", default="auto,1000,2000,4000,8000,16000",
                   help="scene camera exposures to try: auto and/or microseconds")
    d.add_argument("--min-brightness", type=float, default=0.25, help="never go dimmer than this (default 0.25)")
    d.add_argument("--target-brightness", type=float,
                   help="prefer brightness near this (default: the phone's own brightness setting)")
    d.add_argument("--frames", type=int, default=8, help="scene frames scored per setting (default 8)")
    d.add_argument("--wait-s", type=float, default=120.0, help="how long to wait for the app (default 120)")
    d.add_argument("-o", "--out", help="results file (default: analysis_out/display_calibration/<session>.json)")
    d.set_defaults(func=cmd_calibrate_display)

    m = sub.add_parser("simulate", help="write a fake session for a compiled plan (testing without the app)")
    m.add_argument("build", help="compiled study folder")
    m.add_argument("participant", help="participant id, e.g. P001")
    m.add_argument("out", help="session folder to create")
    m.add_argument("--seed", type=int, default=0)
    m.set_defaults(func=cmd_simulate)

    pc = sub.add_parser("phone-check", help="is the phone ready? (optionally for loading a study)")
    pc.add_argument("study", nargs="?", help="study folder to check loading for")
    pc.add_argument("--serial", help="the phone to use when several are connected (see: adb devices)")
    pc.set_defaults(func=cmd_phone_check)

    ld = sub.add_parser("load", help="check, compile and copy a study onto the phone (installs the app if missing)")
    ld.add_argument("study", help="study folder (or its study.yaml)")
    ld.add_argument("--serial", help="the phone to use when several are connected (see: adb devices)")
    ld.add_argument("--update-app", action="store_true", help="also install a newer SocialEyes app if there is one")
    ld.add_argument("--anyway", action="store_true", help="load despite warnings (battery, Do Not Disturb, ...)")
    ld.set_defaults(func=cmd_load)

    ul = sub.add_parser("unload", help="copy the study's sessions off the phone and check them (the phone keeps them)")
    ul.add_argument("study", help="study folder (or its study.yaml)")
    ul.add_argument("--serial", help="the phone to use when several are connected (see: adb devices)")
    ul.add_argument("--clear", action="store_true",
                    help="instead: delete from the phone the sessions whose copies here (and second copy) match it")
    ul.set_defaults(func=cmd_unload)

    wd = sub.add_parser("withdraw", help="withdraw a participant: their data leaves everything (undo: --restore)")
    wd.add_argument("study", help="study folder (or its study.yaml)")
    wd.add_argument("participant", help="participant id")
    wd.add_argument("--reason", help="noted in withdrawals.csv")
    wd.add_argument("--restore", action="store_true", help="undo a withdrawal that hasn't been deleted permanently")
    wd.add_argument("--delete", action="store_true", help="delete a withdrawn participant's data permanently")
    wd.add_argument("--serial", help="the phone, with --delete")
    wd.add_argument("--yes", action="store_true", help="don't ask to confirm")
    wd.set_defaults(func=cmd_withdraw)

    rt = sub.add_parser("retention", help="where the study's data is kept and what its retention rules say is due")
    rt.add_argument("study", help="study folder (or its study.yaml)")
    rt.add_argument("--delete", choices=["face-videos", "sessions"], help="delete what is due (asks to confirm)")
    rt.add_argument("--yes", action="store_true", help="don't ask to confirm")
    rt.set_defaults(func=cmd_retention)

    ex = sub.add_parser("export", help="tidy tables of every session: by session, by item, by condition, with a codebook")
    ex.add_argument("study", help="study folder (or its study.yaml)")
    ex.add_argument("--data", help="the sessions' folder (default: the study's data folder, see: socialeyes folders)")
    ex.add_argument("-o", "--out", help="output folder (default: export/ in the data folder)")
    ex.add_argument("--no-faces", action="store_true",
                    help="don't analyse front camera videos that haven't been analysed yet (their face columns stay blank)")
    ex.add_argument("--unblind", action="store_true",
                    help="show the real condition names in exploration.html (default: neutral codes, so the "
                         "data can be checked without seeing the results)")
    ex.set_defaults(func=cmd_export)

    fo = sub.add_parser("folders", help="show or set where this computer keeps a study's data and second copy")
    fo.add_argument("study", help="study folder (or its study.yaml)")
    fo.add_argument("--data", help="folder for the study's sessions (default: data/<study id>)")
    fo.add_argument("--second-copy", help="folder for a checked second copy of every session, or 'none'")
    fo.add_argument("--clear-after-unload", choices=["on", "off"],
                    help="on: delete each session from the phone as soon as it is unloaded and checked (default off)")
    fo.set_defaults(func=cmd_folders)

    a = sub.add_parser("app", help="open the desktop app (design studies in a window)")
    a.add_argument("--debug", action="store_true", help="allow the browser developer tools (right-click > Inspect)")
    a.set_defaults(func=cmd_app)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
