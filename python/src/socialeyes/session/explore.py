"""A blinded first look at a study's exported tables: exploration.html next to them.

For checking the data before the analysis, without seeing the results: which sessions have
problems (flagged, never excluded here), missing values, each measure's distribution and
outliers, and each measure per condition with the conditions behind neutral codes (condition
A, B, ...; groups X, Y, ...) in an order that says nothing about which is which. No models and no
tests. Unblinding (socialeyes export --unblind, or the app's tick box) shows the real condition
names: a deliberate step, for once the analysis plan is fixed.

The codes come from a shuffle seeded by the study id, so they stay the same from one export to
the next and the pictures can be compared over time; the key is never written down.
"""
from __future__ import annotations

import hashlib
import html
import random
import string
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# by_item measures, in this order when the study has them: (column, label)
ITEM_MEASURES = [
    ("image_weighted_s", "Image time on screen (s, area-weighted)"),
    ("image_visible_s", "Image on screen at all (s)"),
    ("first_seen_s", "First seen, from the start of the feed (s)"),
    ("entries", "Times scrolled into view"),
    ("liked", "Liked (share of posts)"),
    ("comments_opened", "Comments opened"),
    ("comments_sheet_s", "Comments sheet open (s)"),
    ("gaze_image_ms", "Gaze on the image (ms)"),
]
SESSION_MEASURES = [
    ("duration_s", "Session length (s)"),
    ("feed_s", "Time on the feed (s)"),
    ("posts_seen", "Posts seen"),
    ("likes", "Likes"),
    ("comments_opened", "Comments opened"),
]


def _codes(keys: list[str], seed: str, prefix: str, alphabet: str) -> dict[str, str]:
    """Each key's neutral code, in a shuffled order that is the same every time for this seed."""
    order = sorted(keys)
    random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16)).shuffle(order)
    return {k: f"{prefix} {alphabet[i] if i < len(alphabet) else i + 1}" for i, k in enumerate(order)}


def _flags(s: pd.DataFrame) -> pd.DataFrame:
    """Per session, every reason someone might exclude it (none applied here)."""
    s = s.sort_values(["participant_id", "started"]).copy()
    out = pd.DataFrame({"participant_id": s["participant_id"], "session_uid": s["session_uid"]})
    out["not completed"] = s["completed"] != 1
    out["repeat id"] = s.duplicated("participant_id")
    out["background > 30 s"] = s["background_s"].fillna(0) > 30
    out["interrupted"] = s["interruptions"].fillna(0) > 0
    if "face_present" in s:
        out["face < 80%"] = s["face_present"] < 0.8
    if "looking_at_phone" in s:
        out["looking < 70%"] = s["looking_at_phone"] < 0.7
    out["warnings"] = s["n_warnings"].fillna(0).astype(int)
    return out


def _outliers(x: pd.Series) -> Optional[int]:
    """Values beyond 3 interquartile ranges from the middle half; None for yes/no measures."""
    x = x.dropna()
    if x.nunique() <= 2:
        return None
    if len(x) < 4:
        return 0
    q1, q3 = np.percentile(x, [25, 75])
    return int(((x < q1 - 3 * (q3 - q1)) | (x > q3 + 3 * (q3 - q1))).sum())


def _describe(x: pd.Series) -> dict:
    x = x.dropna()
    if not len(x):
        return {"n": 0}
    q1, med, q3 = np.percentile(x, [25, 50, 75])
    return {"n": len(x), "mean": x.mean(), "sd": x.std(ddof=1) if len(x) > 1 else np.nan,
            "median": med, "q1": q1, "q3": q3, "min": x.min(), "max": x.max()}


def _plot(path: Path, groups: dict[str, pd.Series], allvals: pd.Series, label: str, by: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (a, b) = plt.subplots(1, 2, figsize=(9, 3.2), gridspec_kw={"width_ratios": [1, 1.4]})
    vals = allvals.dropna()
    a.hist(vals, bins=min(30, max(5, len(vals) // 5)), color="#7d6ab0")
    a.set_title("all values", fontsize=10)
    names = list(groups)
    data = [groups[n].dropna().to_numpy() for n in names]
    if any(len(d) for d in data):
        b.boxplot([d if len(d) else [np.nan] for d in data], showfliers=False, widths=0.5)
        b.set_xticks(range(1, len(names) + 1), names)  # (boxplot's own labels= was renamed in matplotlib 3.9)
        rng = np.random.default_rng(0)
        for i, d in enumerate(data, 1):
            b.scatter(i + rng.uniform(-0.12, 0.12, len(d)), d, s=10, alpha=0.6, color="#3c5a99")
    b.set_title(f"participant means by {by}", fontsize=10)
    b.tick_params(axis="x", labelsize=8, rotation=20 if len(names) > 4 else 0)
    fig.suptitle(label, fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "–"
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    return f"{v:.3g}" if abs(v) < 1000 else f"{v:.0f}"


def write_exploration(out: Path, tables: dict[str, pd.DataFrame], manifest: dict, columns: dict,
                      unblind: bool = False) -> Path:
    """exploration.html (and exploration/*.png) in ``out``. ``columns`` names the measure columns
    the study has: {"ratings": [...], "questionnaire": [...]}."""
    study = manifest["study"]
    sessions, items = tables["by_session"], tables["by_item"]
    pics = out / "exploration"
    pics.mkdir(parents=True, exist_ok=True)
    for old in pics.glob("*.png"):
        old.unlink()

    flags = _flags(sessions) if len(sessions) else pd.DataFrame()
    crit = items[items["role"] == "critical"].copy() if len(items) else items
    keys = (crit["cell"].fillna("") + (" | " + crit["group_key"].fillna("") if "group_key" in crit else "")).str.strip(" |")
    crit["condition"] = keys
    cond_names = sorted(set(keys))
    cond = {k: k for k in cond_names} if unblind else _codes(cond_names, study["id"] + "/conditions", "condition",
                                                              string.ascii_uppercase)
    groups = sorted(set(sessions["group_key"].fillna(""))) if len(sessions) else []
    grp = {g: (g or "all") for g in groups} if unblind else _codes(groups, study["id"] + "/groups", "group", "XYZWVUTS")

    measures = [(c, l) for c, l in ITEM_MEASURES if c in crit] + \
        [(c, f"Rating: {c}") for c in columns.get("ratings", []) if c in crit] + \
        [(c, f"Recognition correct: {c[:-len('_correct')]}") for c in crit.columns if c.endswith("_correct")] + \
        [(c, f"Gaze on AOI {c[5:-3]} (ms)") for c in crit.columns
         if c.startswith("gaze_") and c.endswith("_ms") and c != "gaze_image_ms"]

    sections, missing = [], []
    for col, label in measures:
        x = pd.to_numeric(crit[col], errors="coerce")
        if x.notna().sum() == 0:
            continue
        missing.append((label, 1 - x.notna().mean(), _outliers(x)))
        per = crit.assign(_y=x).groupby(["participant_id", "condition"])["_y"].mean().reset_index()
        by = {cond[k]: per.loc[per["condition"] == k, "_y"] for k in cond_names}
        by = dict(sorted(by.items()))
        name = f"item_{len(sections):02d}.png"
        _plot(pics / name, by, x, label, "condition")
        rows = "".join(f"<tr><th>{html.escape(g)}</th>" + "".join(f"<td>{_fmt(d.get(k))}</td>" for k in
                       ("n", "mean", "sd", "median", "q1", "q3")) + "</tr>"
                       for g, d in ((g, _describe(v)) for g, v in by.items()))
        sections.append(f"""<section><h3>{html.escape(label)}</h3><img src="exploration/{name}" alt="{html.escape(label)}">
          <table><tr><th></th><th>participants</th><th>mean</th><th>SD</th><th>median</th><th>Q1</th><th>Q3</th></tr>{rows}</table></section>""")

    s_measures = [(c, l) for c, l in SESSION_MEASURES if c in sessions] + \
        [(c, f"Questionnaire: {c}") for c in columns.get("questionnaire", []) if c in sessions]
    s_sections = []
    for col, label in s_measures:
        x = pd.to_numeric(sessions[col], errors="coerce")
        if x.notna().sum() == 0:
            continue
        missing.append((label + " (per session)", 1 - x.notna().mean(), _outliers(x)))
        by = dict(sorted({grp[g]: x[sessions["group_key"].fillna("") == g] for g in groups}.items()))
        name = f"session_{len(s_sections):02d}.png"
        _plot(pics / name, by, x, label, "group")
        rows = "".join(f"<tr><th>{html.escape(g)}</th>" + "".join(f"<td>{_fmt(d.get(k))}</td>" for k in
                       ("n", "mean", "sd", "median", "q1", "q3")) + "</tr>"
                       for g, d in ((g, _describe(v)) for g, v in by.items()))
        s_sections.append(f"""<section><h3>{html.escape(label)}</h3><img src="exploration/{name}" alt="{html.escape(label)}">
          <table><tr><th></th><th>sessions</th><th>mean</th><th>SD</th><th>median</th><th>Q1</th><th>Q3</th></tr>{rows}</table></section>""")

    flag_cols = [c for c in flags.columns if c not in ("participant_id", "session_uid")]
    flagged = flags[flags[flag_cols].astype(bool).any(axis=1)] if len(flags) else flags
    flag_rows = "".join(
        "<tr><td>" + html.escape(str(r["participant_id"])) + "</td>" + "".join(
            f"<td class={'on' if (r[c] if c != 'warnings' else r[c] > 0) else ''}>"
            f"{'✓' if (c != 'warnings' and r[c]) else (r[c] if c == 'warnings' and r[c] else '')}</td>" for c in flag_cols) + "</tr>"
        for _, r in flagged.iterrows())
    flag_counts = ", ".join(f"{c}: {int((flags[c] > 0).sum() if c == 'warnings' else flags[c].sum())}" for c in flag_cols)
    miss_rows = "".join(f"<tr><th>{html.escape(l)}</th><td>{100 * m:.1f}%</td><td>{'–' if o is None else o}</td></tr>"
                        for l, m, o in missing)
    banner = ("<p class=unblind><b>Unblinded:</b> the real condition names are shown.</p>" if unblind else
              "<p class=blind><b>Blinded.</b> Conditions are shown as codes in a shuffled order. Unblind only once your "
              "analysis plan is fixed: <code>socialeyes export --unblind</code>, or tick <i>Unblind</i> under Data in the app.</p>")
    page = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Data exploration</title>
<style>
:root{{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#ddd;--soft:#f4f1fa;--warn:#8a5a00;--warn-soft:#fff4dc}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151515;--fg:#eee;--muted:#aaa;--line:#333;--soft:#211d2b;--warn:#f5c56b;--warn-soft:#3a2c0b}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:1000px;padding:16px}}
h2{{margin-top:36px;border-top:1px solid var(--line);padding-top:16px}} h3{{margin:24px 0 6px;font-size:16px}}
img{{max-width:100%;background:#fff;border-radius:8px}} .table-wrap{{overflow-x:auto}}
table{{border-collapse:collapse;font-size:13px;margin:6px 0}} th,td{{padding:4px 10px;border-bottom:1px solid var(--line);text-align:left}}
td.on{{background:var(--warn-soft);color:var(--warn);font-weight:600}} .muted{{color:var(--muted)}}
.blind,.unblind{{padding:10px 14px;border-radius:10px;background:var(--soft)}} .unblind{{background:var(--warn-soft);color:var(--warn)}}
</style>
<h1>Data exploration: {html.escape(study.get('title') or study['id'])}</h1>
{banner}
<p class=muted>A look at the data before the analysis: nothing here is a test, and nothing is excluded.
Each condition's numbers are participants' means over its posts (critical posts only).</p>
<h2>Sessions</h2>
<p>{len(sessions)} session(s). Flags (decide your exclusion rules in your analysis plan): {html.escape(flag_counts) or "none"}.</p>
{f"<div class=table-wrap><table><tr><th>participant</th>{''.join(f'<th>{html.escape(c)}</th>' for c in flag_cols)}</tr>{flag_rows}</table></div>"
   if len(flagged) else "<p class=muted>No session flagged.</p>"}
<h2>Missing values and outliers</h2>
<p class=muted>Outliers: beyond 3 interquartile ranges from the middle half.</p>
<table><tr><th></th><th>missing</th><th>outliers</th></tr>{miss_rows}</table>
<h2>Per post</h2>{''.join(sections) or '<p>No measures yet.</p>'}
<h2>Per session</h2>{''.join(s_sections) or '<p>No measures yet.</p>'}
"""
    path = out / "exploration.html"
    path.write_text(page, encoding="utf-8")
    return path
