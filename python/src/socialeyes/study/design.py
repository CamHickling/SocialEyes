"""Counterbalancing, participant assignment and feed ordering.

Everything here is a pure function of (study, participant number) so that a plan
can be regenerated and audited at any time.

Design logic
------------
* Within-subject factors are fully crossed into *cells* (e.g. edit x label ->
  4 cells). Critical posts are rotated through the cells across counterbalancing
  *lists* (a Latin-square rotation): in list L, critical post i gets cell
  (i + L) mod n_cells. So every participant sees every critical post exactly once,
  and across lists every post appears in every cell equally often.
* Between-subject factors are fully crossed into *groups*.
* Participants are assigned to (group, list) pairs by blocked randomisation: each
  consecutive block of n_groups * n_lists participants contains every pair once,
  in a random (seeded) order. Running any multiple of the block size gives a
  perfectly balanced design; stopping mid-block leaves at most one imbalance.
"""
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass

from .schema import Factor, Feed, Study


@dataclass(frozen=True)
class Cell:
    levels: tuple[tuple[str, str], ...]  # ((factor, level), ...)

    @property
    def key(self) -> str:
        return "|".join(f"{f}={l}" for f, l in self.levels) or "all"

    def as_dict(self) -> dict[str, str]:
        return dict(self.levels)


def cells(factors: list[Factor]) -> list[Cell]:
    if not factors:
        return [Cell(())]
    combos = itertools.product(*[[(f.name, l) for l in f.levels] for f in factors])
    return [Cell(tuple(c)) for c in combos]


@dataclass(frozen=True)
class Assignment:
    participant_index: int  # 0-based
    group: int
    list: int
    between: dict[str, str]


def assignment_schedule(study: Study, n: int) -> list[Assignment]:
    groups = cells(study.between)
    n_lists = len(cells(study.within))
    pairs = [(g, l) for g in range(len(groups)) for l in range(n_lists)]
    rng = random.Random(f"{study.seed}:assignment")
    out: list[Assignment] = []
    while len(out) < n:
        block = pairs[:]
        rng.shuffle(block)
        for g, l in block:
            if len(out) == n:
                break
            out.append(Assignment(len(out), g, l, groups[g].as_dict()))
    return out


def cell_for(critical_index: int, list_index: int, n_cells: int) -> int:
    return (critical_index + list_index) % n_cells


def participant_rng(study: Study, participant_id: str, purpose: str) -> random.Random:
    return random.Random(f"{study.seed}:{participant_id}:{purpose}")


def order_feed(
    critical: list[tuple[str, str]],
    fillers: list[str],
    feed: Feed,
    rng: random.Random,
) -> list[str]:
    """Order post ids. ``critical`` is [(post_id, cell_key)].

    Constraints: ``lead_in_fillers`` fillers first; among critical posts (taken in
    feed order) no more than ``max_run_same_cell`` consecutive share a cell (when
    there is more than one cell); at
    least ``min_fillers_between_critical`` fillers between consecutive critical
    posts. Raises ValueError if the constraints cannot be met.
    """
    if feed.order == "fixed":
        raise ValueError("order_feed is only used for order: shuffle")
    fillers = fillers[:]
    rng.shuffle(fillers)
    if feed.lead_in_fillers > len(fillers):
        raise ValueError(f"feed.lead_in_fillers={feed.lead_in_fillers} but only {len(fillers)} filler posts")
    lead, rest = fillers[: feed.lead_in_fillers], fillers[feed.lead_in_fillers :]

    crit = critical[:]
    # With a single cell (no within-subject factor) every critical post shares it,
    # so the run rule can't apply; just shuffle.
    one_cell = len({c for _, c in crit}) <= 1
    for _ in range(20000):
        rng.shuffle(crit)
        if one_cell or _max_run([c for _, c in crit]) <= feed.max_run_same_cell:
            break
    else:
        raise ValueError(
            f"could not satisfy max_run_same_cell={feed.max_run_same_cell}; "
            "add critical posts or relax the constraint"
        )

    m = feed.min_fillers_between_critical
    n_gaps_internal = max(len(crit) - 1, 0)
    if m * n_gaps_internal > len(rest):
        raise ValueError(
            f"min_fillers_between_critical={m} needs {m * n_gaps_internal} fillers after the lead-in; "
            f"only {len(rest)} available"
        )
    # gaps[0] = before first critical, gaps[k] = after k-th critical.
    gaps = [0] + [m] * n_gaps_internal + [0] if crit else [0]
    for _ in range(len(rest) - m * n_gaps_internal):
        gaps[rng.randrange(len(gaps))] += 1

    order = list(lead)
    it = iter(rest)
    order += [next(it) for _ in range(gaps[0])]
    for k, (pid, _) in enumerate(crit):
        order.append(pid)
        order += [next(it) for _ in range(gaps[k + 1])]
    return order


def _max_run(seq: list[str]) -> int:
    best = run = 0
    prev = object()
    for s in seq:
        run = run + 1 if s == prev else 1
        best = max(best, run)
        prev = s
    return best


def validation_points(n: int) -> list[tuple[float, float]]:
    """Normalised (x, y) screen positions, inset from the edges."""
    lo, mid, hi = 0.1, 0.5, 0.9
    grid9 = [(x, y) for y in (lo, mid, hi) for x in (lo, mid, hi)]
    if n == 5:
        return [(mid, mid), (lo, lo), (hi, lo), (lo, hi), (hi, hi)]
    if n == 9:
        return grid9
    return grid9 + [(0.3, 0.3), (0.7, 0.3), (0.3, 0.7), (0.7, 0.7)]


def m_sequence(degree: int = 7, taps: tuple[int, ...] | None = None, seed: int = 1) -> list[int]:
    """Maximal-length binary sequence (period 2**degree - 1) from a Fibonacci LFSR.

    Its autocorrelation has a single sharp peak, which makes the time shift
    between the logged code and the code seen in the scene video unambiguous.
    """
    default_taps = {5: (5, 3), 6: (6, 5), 7: (7, 6), 8: (8, 6, 5, 4), 9: (9, 5), 10: (10, 7)}
    taps = taps or default_taps[degree]
    state = seed or 1
    out = []
    for _ in range(2**degree - 1):
        out.append(state & 1)
        fb = 0
        for t in taps:
            fb ^= (state >> (degree - t)) & 1
        state = (state >> 1) | (fb << (degree - 1))
    return out
