"""The ``socialeyes`` command-line tool.

    socialeyes validate STUDY_DIR
    socialeyes compile STUDY_DIR [-o OUT] [--clean]
    socialeyes case-sheet --width-mm W --height-mm H [--study STUDY_DIR] [-o case_sheet.svg]
    socialeyes session SESSION_DIR [--build BUILD_DIR] [-o OUT]
    socialeyes simulate BUILD_DIR PARTICIPANT_ID OUT_DIR [--seed N]
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

    m = sub.add_parser("simulate", help="write a fake session for a compiled plan (testing without the app)")
    m.add_argument("build", help="compiled study folder")
    m.add_argument("participant", help="participant id, e.g. P001")
    m.add_argument("out", help="session folder to create")
    m.add_argument("--seed", type=int, default=0)
    m.set_defaults(func=cmd_simulate)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
