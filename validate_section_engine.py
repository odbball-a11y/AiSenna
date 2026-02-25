#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_section_engine.py
==========================
Standalone validation harness for the Section Engine (Phase 2, Option A).

Loads real Silverstone laps, builds a CoachingEngine, simulates slow laps
through the engine with a synthetic clock, and prints the radio transcript
the driver would hear — including Maggots-Becketts diagnostic.

No production code is modified. Engine runs in simulation mode only.

Usage:
    python validate_section_engine.py
"""

import sys
import os
import logging
from collections import deque
from typing import List, Optional, Dict

# ── Project root on path ───────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from senna_ai.data.lap_scanner import scan_lap_files
from senna_ai.telemetry.models import TelPoint, LapTrace, RefLapFile
import senna_ai.coaching.engine as _engine_module
from senna_ai.coaching.engine import CoachingEngine
from senna_ai.track.complex_detection import Complex

# ── Config ─────────────────────────────────────────────────────────────────
SILVERSTONE_FOLDER    = "senna_ai/opponent_laps/Silverstone Grand Prix Circuit - ELMS"
SLOW_LAP_THRESHOLD_S  = 0.5   # seconds slower than fastest to qualify as "slow"
N_SLOW_LAPS           = 3     # how many slow laps to simulate
MAX_REF_LAPS          = 50    # how many reference laps to feed the composite

# Only route logging from our harness; suppress engine noise
logging.basicConfig(level=logging.WARNING)
log = logging.getLogger("validate_section_engine")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Mock Speaker
# ─────────────────────────────────────────────────────────────────────────────

class MockSpeaker:
    """Silent drop-in for tts_engine.Speaker."""
    def say(self, text: str):          pass
    def say_priority(self, text: str): pass


# ─────────────────────────────────────────────────────────────────────────────
# 2. Timestamp helpers
# ─────────────────────────────────────────────────────────────────────────────

def compute_timestamps(points: List[TelPoint], base_time: float = 1000.0) -> List[float]:
    """
    Integrate distance / average-speed to produce realistic wall-clock
    timestamps for every point in the lap.  Returns one float per point.
    """
    if not points:
        return []
    ts = [base_time]
    for i in range(1, len(points)):
        prev, curr = points[i - 1], points[i]
        d_dist = curr.dist_m - prev.dist_m
        # Wrap-around guard: skip backwards jumps > 500 m
        if d_dist < 0 or d_dist > 500:
            ts.append(ts[-1])
            continue
        avg_mps = ((prev.speed_kph + curr.speed_kph) / 2.0) / 3.6
        if avg_mps < 0.5:
            avg_mps = 0.5          # never divide by near-zero
        ts.append(ts[-1] + d_dist / avg_mps)
    return ts


def compute_section_time(points: List[TelPoint], cx: Complex) -> Optional[float]:
    """
    Integrate distance / speed through a section to compute transit time.
    Returns None if there is insufficient data.
    """
    inside = [p for p in points if cx.start_m <= p.dist_m <= cx.end_m]
    if len(inside) < 2:
        return None
    total = 0.0
    for i in range(1, len(inside)):
        d = inside[i].dist_m - inside[i - 1].dist_m
        if d <= 0 or d > 300:      # skip wrap/teleport
            continue
        avg_mps = ((inside[i].speed_kph + inside[i - 1].speed_kph) / 2.0) / 3.6
        if avg_mps < 0.5:
            avg_mps = 0.5
        total += d / avg_mps
    return total if total > 0.1 else None


# ─────────────────────────────────────────────────────────────────────────────
# 3. Engine helpers
# ─────────────────────────────────────────────────────────────────────────────

def build_engine(laps: List[RefLapFile]) -> CoachingEngine:
    """
    Build a CoachingEngine from reference laps, start it, and force-prime
    _corner_ready so coaching cues fire from the very first simulated lap.
    """
    engine = CoachingEngine(speaker=MockSpeaker())
    engine.set_reference_laps(laps)
    engine.start()
    # Prime: mark every corner as 'seen' so approach / post cues activate
    engine._corner_ready = set(c.index for c in engine.corners)
    # Ensure the focus gate is open (all sections + corners active)
    engine.lap_focus_entities = set()
    return engine


def populate_prev_data(engine: CoachingEngine, ref_lap: RefLapFile) -> None:
    """
    Seed engine._prev_corner_data with reference-lap corner zones so that
    _get_section_bottleneck() has apex-speed data on the very first simulated
    slow lap (without needing to 'warm up' a real lap first).
    """
    pts = ref_lap.trace.points
    for corner in engine.corners:
        zone = [
            p for p in pts
            if corner.brake_point_m - 100 <= p.dist_m <= corner.exit_m + 100
        ]
        if len(zone) >= 5:
            engine._prev_corner_data[corner.index] = zone


def seed_section_history(engine: CoachingEngine, ref_lap: RefLapFile) -> None:
    """
    Compute one 'reference lap' section time per complex from the fastest lap
    and insert it into _section_lap_times / _section_best_time.

    This ensures _check_section_post_cue sees ≥ 2 history entries on the
    FIRST simulated slow lap and therefore fires a post-section assessment.
    """
    pts = ref_lap.trace.points
    for cx in engine.complexes:
        t = compute_section_time(pts, cx)
        if t is None:
            continue
        engine._section_lap_times[cx.index] = deque([t], maxlen=5)
        engine._section_best_time[cx.index] = t


# ─────────────────────────────────────────────────────────────────────────────
# 4. Simulation
# ─────────────────────────────────────────────────────────────────────────────

# Shared mutable clock used by the fake time.time()
_sim_clock: List[float] = [0.0]

def _fake_time() -> float:
    return _sim_clock[0]


def simulate_lap(
    engine: CoachingEngine,
    lap: RefLapFile,
    base_time: float = 1000.0,
) -> List[Dict]:
    """
    Feed all points from *lap* through the engine and capture every _speak()
    call. Returns a list of event dicts:
        {'text', 'source', 'dist', 'priority'}

    Key techniques:
    - engine._speak is replaced on the instance with a capturing closure
      (restored in finally so subsequent laps work correctly).
    - time.time in the engine module is monkey-patched to return synthetic
      timestamps derived from speed/distance integration, so that
      _update_section_timing() computes realistic section transit times.
    """
    captured: List[Dict] = []
    pts = lap.trace.points
    if not pts:
        return captured

    # Pre-compute synthetic timestamps for this lap
    timestamps = compute_timestamps(pts, base_time=base_time)
    _sim_clock[0] = base_time

    # ── Capture closure ───────────────────────────────────────────────────
    def capturing_speak(text: str, source: str, priority: bool = False):
        captured.append({
            'text':     text,
            'source':   source,
            'dist':     engine.live_dist,
            'priority': priority,
        })
    # Override _speak on the engine instance (bypasses TTS; captures source)
    engine._speak = capturing_speak  # type: ignore[method-assign]

    # ── Per-lap reset (mirrors what crossed_line normally does) ───────────
    engine._approach_fired.clear()
    engine._post_fired.clear()
    engine._section_approach_fired.clear()
    engine._section_post_fired.clear()
    engine._section_enter_time.clear()
    engine._section_exit_time.clear()
    engine._corner_advice_type.clear()
    engine.corner_events_this_lap.clear()
    engine.speeches_this_lap.clear()
    engine.entities_spoken_this_lap.clear()
    engine._last_dist = 0.0
    engine.lap_focus_entities = set()   # open gate

    # ── Patch time.time so point.timestamp uses synthetic clock ───────────
    _real_time_fn = _engine_module.time.time
    _engine_module.time.time = _fake_time  # type: ignore[attr-defined]

    try:
        for i, pt in enumerate(pts):
            _sim_clock[0] = timestamps[i]
            engine.feed(
                dist_m    = pt.dist_m,
                speed_kph = pt.speed_kph,
                speed_mps = pt.speed_kph / 3.6,
                throttle  = pt.throttle_pct / 100.0,
                brake     = pt.brake_pct    / 100.0,
                steer     = pt.steer_pct    / 100.0,
                gear      = pt.gear,
            )
    finally:
        # Restore time.time and _speak
        _engine_module.time.time = _real_time_fn  # type: ignore[attr-defined]
        try:
            del engine._speak          # removes instance attr; class method restored
        except AttributeError:
            pass

    return captured


# ─────────────────────────────────────────────────────────────────────────────
# 5. Lap selection
# ─────────────────────────────────────────────────────────────────────────────

def select_slow_laps(
    laps_sorted: List[RefLapFile],
    fastest_time: float,
    count: int = N_SLOW_LAPS,
) -> List[RefLapFile]:
    """
    Pick *count* laps that are at least SLOW_LAP_THRESHOLD_S slower than the
    fastest.  Spreads selection across the available range (fastest-slow,
    mid-slow, slowest) for maximum diagnostic coverage.
    """
    candidates = [
        l for l in laps_sorted
        if l.lap_time >= fastest_time + SLOW_LAP_THRESHOLD_S
    ]
    if not candidates:
        return []
    if len(candidates) <= count:
        return candidates
    # Evenly spaced across the candidate list
    step = (len(candidates) - 1) / (count - 1)
    return [candidates[int(round(i * step))] for i in range(count)]


# ─────────────────────────────────────────────────────────────────────────────
# 6. Output formatters
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_time(t: float) -> str:
    m = int(t) // 60
    s = t - m * 60
    return f"{m}:{s:06.3f}" if m > 0 else f"{s:.3f}s"


def _find_maggots_complex(engine: CoachingEngine) -> Optional[Complex]:
    """Heuristic: find the Maggots-Becketts complex by name or by type=esses."""
    keywords = ("maggots", "becketts", "chapel")
    for cx in engine.complexes:
        if any(k in cx.name.lower() for k in keywords):
            return cx
    # Fallback: pick the fastest esses complex (highest avg speed)
    esses = [cx for cx in engine.complexes if cx.complex_type == "esses"]
    if esses:
        return max(esses, key=lambda c: c.avg_speed_kph)
    return None


def print_section_summary(engine: CoachingEngine, fastest: RefLapFile) -> None:
    print()
    print("═" * 72)
    print("  SECTION DETECTION SUMMARY")
    print("═" * 72)
    print(f"  Track  : {fastest.track_name}")
    print(f"  Corners: {len(engine.corners)}")
    print(f"  Sections detected: {len(engine.complexes)}")
    print()
    for cx in engine.complexes:
        hist = engine._section_lap_times.get(cx.index)
        ref_str = f"{list(hist)[0]:.2f}s" if hist else "n/a"
        c_str = "T" + ",T".join(str(i) for i in cx.corner_indices)
        # Post-hoc metrics from _compute_complex_metrics (ground-truth cross-check)
        steer_col = (f"  steer_rms={cx.steering_rms:.1f}%  dir_changes={cx.n_direction_changes}"
                     if getattr(cx, "steering_rms", 0) > 0 else "")
        print(
            f"  [{cx.index}] {cx.name:<38} {cx.complex_type:<14} "
            f"{c_str:<18} ref={ref_str}{steer_col}"
        )
    print()


def print_transcript(lap: RefLapFile, events: List[Dict], lap_num: int) -> None:
    print("─" * 72)
    delta_str = f"+{lap.lap_time - 0:.3f}"  # filled in by caller
    print(f"  LAP {lap_num}  |  {_fmt_time(lap.lap_time)}  |  {lap.car_name[:45]}")
    print("─" * 72)
    if not events:
        print("  [no cues fired this lap]")
    else:
        for ev in events:
            tag = "▶ PRIORITY" if ev['priority'] else "  normal  "
            src = ev['source']
            # Categorise for readability
            if "section_approach" in src:
                cat = "SECTION-IN "
            elif "section_post" in src:
                cat = "SECTION-OUT"
            elif "approach_cue" in src:
                cat = "corner-in  "
            elif "post_feedback" in src:
                cat = "corner-out "
            elif "lap_completion" in src:
                cat = "lap        "
            elif "start_coaching" in src:
                cat = "start      "
            else:
                cat = "other      "
            print(f"  [{tag}] @{ev['dist']:6.0f}m  {cat}  \"{ev['text']}\"")
    print()


def print_maggots_diagnostic(
    engine: CoachingEngine,
    mb_cx: Optional[Complex],
    lap: RefLapFile,
    events: List[Dict],
    lap_num: int,
) -> None:
    print(f"  ┌── Maggots-Becketts Diagnostic  —  Lap {lap_num}  ({_fmt_time(lap.lap_time)})")
    if mb_cx is None:
        print("  │   No Maggots-Becketts complex detected (check complex_detection)")
        print("  └──")
        print()
        return

    lap_sec_t = compute_section_time(lap.trace.points, mb_cx)
    history   = engine._section_lap_times.get(mb_cx.index)
    hist_list = list(history) if history else []
    best_t    = engine._section_best_time.get(mb_cx.index, 0.0)

    approach_ev = [e for e in events if f"section_approach_{mb_cx.index}" in e['source']]
    post_ev     = [e for e in events if f"section_post_{mb_cx.index}"     in e['source']]

    print(f"  │   Section : {mb_cx.name}")
    print(f"  │   Type    : {mb_cx.complex_type}")
    print(f"  │   Span    : {mb_cx.start_m:.0f}m → {mb_cx.end_m:.0f}m")
    print(f"  │   Corners : T{',T'.join(str(i) for i in mb_cx.corner_indices)}")
    if lap_sec_t:
        print(f"  │   Lap time: {lap_sec_t:.3f}s")
    else:
        print("  │   Lap time: n/a (insufficient points in zone)")
    print(f"  │   History : {[f'{t:.3f}s' for t in hist_list]}")
    print(f"  │   Best    : {best_t:.3f}s" if best_t else "  │   Best    : n/a")

    if approach_ev:
        for ev in approach_ev:
            print(f"  │   ▶ APPROACH @ {ev['dist']:.0f}m : \"{ev['text']}\"")
    else:
        print("  │   ✗ Approach cue did NOT fire")

    if post_ev:
        for ev in post_ev:
            print(f"  │   ▶ POST     @ {ev['dist']:.0f}m : \"{ev['text']}\"")
    else:
        print("  │   ✗ Post cue did NOT fire  "
              "(need ≥2 history entries — seeded from ref lap + current lap)")

    # Bottleneck uses _prev_corner_data — still points at ref lap for lap 1
    bottleneck_idx = engine._get_section_bottleneck(mb_cx)
    if bottleneck_idx:
        corner_obj = next((c for c in mb_cx.corners if c.index == bottleneck_idx), None)
        name_str   = ""  # Corner has no .name attribute
        print(f"  │   Bottleneck: T{bottleneck_idx}{name_str}")
    else:
        print("  │   Bottleneck: none (no _prev_corner_data for this complex yet)")

    # Check suppression: corner cues inside the section should be absent
    section_corner_ids = set(mb_cx.corner_indices)
    suppressed = [
        e for e in events
        if "approach_cue" in e['source']
        and any(f"_C{ci}" in e['source'] for ci in section_corner_ids)
    ]
    print(f"  │   Corner cues INSIDE section: {len(suppressed)} "
          f"({'✓ all suppressed' if not suppressed else '✗ some leaked through'})")
    print("  └──")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# 7. Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print()
    print("═" * 72)
    print("  SENNA AI — Section Engine Validation Harness")
    print("  Phase 2 · Option A: Section owns the speech slot")
    print("═" * 72)

    # ── Load laps ──────────────────────────────────────────────────────────
    print(f"\n  Loading: {SILVERSTONE_FOLDER}")
    laps, errors = scan_lap_files(SILVERSTONE_FOLDER)
    if errors:
        print(f"  ⚠  {len(errors)} load error(s) — first: {errors[0]}")
    if not laps:
        print("  ✗  No laps loaded. Aborting.")
        sys.exit(1)

    laps_sorted = sorted(laps, key=lambda l: l.lap_time)
    fastest     = laps_sorted[0]
    slowest     = laps_sorted[-1]
    print(f"  ✓  {len(laps)} laps loaded")
    print(f"     Fastest : {_fmt_time(fastest.lap_time)}  ({fastest.car_name[:45]})")
    print(f"     Slowest : {_fmt_time(slowest.lap_time)}")
    print(f"     Track   : {fastest.track_name}")

    # ── Build engine ───────────────────────────────────────────────────────
    print(f"\n  Building engine from {min(MAX_REF_LAPS, len(laps))} ref laps…")
    engine = build_engine(laps_sorted[:MAX_REF_LAPS])
    print(f"  ✓  {len(engine.corners)} corners  ·  {len(engine.complexes)} sections")

    # ── Seed reference data ────────────────────────────────────────────────
    populate_prev_data(engine, fastest)
    seed_section_history(engine, fastest)
    print("  ✓  Reference data seeded")

    # ── Section summary ────────────────────────────────────────────────────
    print_section_summary(engine, fastest)

    # Identify Maggots-Becketts for the dedicated diagnostic
    mb_cx = _find_maggots_complex(engine)
    if mb_cx:
        print(f"  Maggots-Becketts complex identified: [{mb_cx.index}] {mb_cx.name}")
    else:
        print("  ⚠  Maggots-Becketts complex not identified by name — will use esses fallback")
    print()

    # ── Select slow laps ───────────────────────────────────────────────────
    slow_laps = select_slow_laps(laps_sorted, fastest.lap_time, count=N_SLOW_LAPS)
    if not slow_laps:
        print(f"  ✗  No laps ≥ {SLOW_LAP_THRESHOLD_S}s slower than fastest. Aborting.")
        sys.exit(1)

    print(f"  Selected {len(slow_laps)} slow laps to simulate:")
    for i, sl in enumerate(slow_laps, 1):
        delta = sl.lap_time - fastest.lap_time
        print(f"    Lap {i}: {_fmt_time(sl.lap_time)}  (+{delta:.2f}s)  {sl.car_name[:45]}")

    # ── Simulate + transcript ──────────────────────────────────────────────
    print()
    print("═" * 72)
    print("  RADIO TRANSCRIPTS")
    print("═" * 72)

    all_events: List[List[Dict]] = []
    base_time = 1000.0   # arbitrary non-zero start

    for lap_num, slow_lap in enumerate(slow_laps, 1):
        events = simulate_lap(engine, slow_lap, base_time=base_time)
        all_events.append(events)

        # Step the synthetic clock forward for the next lap
        base_time += slow_lap.lap_time + 10.0   # 10 s gap between laps

        # Carry corner data forward so subsequent laps have prev-lap bottleneck data
        engine._prev_corner_data = {k: list(v) for k, v in engine._corner_data.items()}

        print_transcript(slow_lap, events, lap_num)

    # ── Maggots-Becketts diagnostic ────────────────────────────────────────
    print("═" * 72)
    print("  MAGGOTS-BECKETTS DIAGNOSTIC  (per simulated lap)")
    print("═" * 72)
    print()
    for lap_num, (slow_lap, events) in enumerate(zip(slow_laps, all_events), 1):
        print_maggots_diagnostic(engine, mb_cx, slow_lap, events, lap_num)

    # ── Conclusion ─────────────────────────────────────────────────────────
    print("═" * 72)
    print("  CONCLUSION")
    print("═" * 72)

    n_section_approach = sum(
        1 for evs in all_events for e in evs if "section_approach" in e["source"]
    )
    n_section_post = sum(
        1 for evs in all_events for e in evs if "section_post" in e["source"]
    )
    n_corner_approach = sum(
        1 for evs in all_events for e in evs if "approach_cue" in e["source"]
    )
    n_corner_post = sum(
        1 for evs in all_events for e in evs if "post_feedback" in e["source"]
    )
    n_section_corner_approach_leaked = sum(
        1 for evs in all_events for e in evs
        if "approach_cue" in e["source"] and mb_cx
        and any(f"_C{ci}" in e["source"] for ci in mb_cx.corner_indices)
    )

    print()
    print(f"  Section approach cues fired       : {n_section_approach}")
    print(f"  Section post cues fired           : {n_section_post}")
    print(f"  Corner approach cues (all)        : {n_corner_approach}")
    print(f"  Corner post cues (all)            : {n_corner_post}")
    if mb_cx:
        print(f"  Corner cues inside M-B section    : {n_section_corner_approach_leaked} "
              f"(should be 0)")
    print()

    checks = [
        (
            f"Section approach cue fired in ≥1 lap",
            n_section_approach >= 1,
        ),
        (
            "Section post cue fired in ≥1 lap  (requires seeded history)",
            n_section_post >= 1,
        ),
        (
            "Corner cues inside M-B section suppressed",
            mb_cx is None or n_section_corner_approach_leaked == 0,
        ),
    ]

    all_pass = True
    for label, passed in checks:
        icon = "✓" if passed else "✗"
        print(f"  {icon}  {label}")
        if not passed:
            all_pass = False

    print()
    outcome = "✅  PASS — Section Engine is wired correctly." if all_pass \
              else "❌  FAIL — Check the diagnostics above."
    print(f"  {outcome}")
    print("═" * 72)
    print()


if __name__ == "__main__":
    main()
