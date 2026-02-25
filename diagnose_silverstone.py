#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnose_silverstone.py
=======================
Forensic diagnostic — telemetry truth extraction.

Exposes:
  PART 1  Reference lap sanity check + filtered reference set
  PART 2  Maggots-Becketts flow-zone forensic (per-lap metrics)
  PART 3  Consensus instability (speed-minima distribution + apex variance)
  PART 4  Reset logic debug (verbose _detect_driver_reset replication)
  PART 5  Final diagnostic — 6 explicit numbered answers

No production code is modified. Read-only.

Usage:
    python diagnose_silverstone.py
"""

import sys
import os
import math
import statistics
from collections import Counter, deque
from typing import List, Optional, Dict, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from senna_ai.data.lap_scanner import scan_lap_files
from senna_ai.telemetry.models import TelPoint, LapTrace, RefLapFile
from senna_ai.coaching.engine import CoachingEngine
from senna_ai.track.complex_detection import Complex

import logging
logging.basicConfig(level=logging.WARNING)

SILVERSTONE_FOLDER = "senna_ai/opponent_laps/Silverstone Grand Prix Circuit - ELMS"
TARGET_LAP_S       = 83.380      # 1:23.380 — the suspicious fastest lap
MAX_REF_LAPS       = 50          # engine reference pool size

# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _fmt(t: float) -> str:
    m = int(t) // 60
    s = t - m * 60
    return f"{m}:{s:06.3f}" if m > 0 else f"{s:.3f}s"

def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    sv = sorted(values)
    idx = max(0, min(len(sv) - 1, int(len(sv) * pct / 100.0)))
    return sv[idx]

def _kmeans1d_lower(values: List[float], k: int = 2) -> List[float]:
    """Simple 1-D k-means, returns values in the lowest cluster."""
    sv = sorted(values)
    # Find the largest gap — that's the natural cluster boundary
    gaps = [(sv[i+1] - sv[i], i) for i in range(len(sv) - 1)]
    gaps.sort(reverse=True)
    # Take top (k-1) boundaries
    boundaries = sorted([sv[i] + (sv[i+1]-sv[i])/2 for _, i in gaps[:k-1]])
    return [v for v in sv if v < boundaries[0]]


class _MockSpeaker:
    def say(self, text):          pass
    def say_priority(self, text): pass


def _build_engine(ref_laps: List[RefLapFile]) -> CoachingEngine:
    engine = CoachingEngine(speaker=_MockSpeaker())
    engine.set_reference_laps(ref_laps)
    return engine


# ─────────────────────────────────────────────────────────────────────────────
# PART 1 helpers
# ─────────────────────────────────────────────────────────────────────────────

def _lap_stats(laps: List[RefLapFile]) -> dict:
    times = [l.lap_time for l in laps]
    mean_t   = statistics.mean(times)
    median_t = statistics.median(times)
    std_t    = statistics.stdev(times) if len(times) > 1 else 0.0
    return dict(
        mean=mean_t, median=median_t, std=std_t,
        p5 =_percentile(times,  5),
        p25=_percentile(times, 25),
        p75=_percentile(times, 75),
        p95=_percentile(times, 95),
        lo_threshold=median_t - 3 * std_t,
        hi_threshold=median_t + 3 * std_t,
    )

def _filtered_sets(laps: List[RefLapFile], st: dict) -> dict:
    times = [l.lap_time for l in laps]
    # Option A: p5 to p25
    opt_a = [l for l in laps if st['p5'] <= l.lap_time <= st['p25']]
    # Option B: lower k-means cluster
    lower_times = set(_kmeans1d_lower(times, k=2))
    opt_b = [l for l in laps if l.lap_time in lower_times]
    # Option C: <= p25 + 1.5s  ← used for clean engine
    opt_c = [l for l in laps if l.lap_time <= st['p25'] + 1.5]
    return dict(A=opt_a, B=opt_b, C=opt_c)

def _plausibility(lap: RefLapFile) -> Tuple[float, float, str]:
    max_spd = max((p.speed_kph for p in lap.trace.points), default=0.0)
    tl = lap.track_length if lap.track_length > 0 else 5869.0
    avg_spd = (tl / lap.lap_time) * 3.6 if lap.lap_time > 0 else 0.0
    verdict = "SUSPICIOUS" if avg_spd > 200.0 else "plausible"
    return max_spd, avg_spd, verdict


# ─────────────────────────────────────────────────────────────────────────────
# PART 2 helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_maggots_cx(engine: CoachingEngine) -> Optional[Complex]:
    """Return fastest-average-speed multi-corner complex — proxy for Maggots."""
    multi = [cx for cx in engine.complexes if len(cx.corner_indices) >= 2]
    if not multi:
        return engine.complexes[-1] if engine.complexes else None
    # Prefer 'esses' type; otherwise highest avg_speed_kph
    esses = [cx for cx in multi if cx.complex_type == 'esses']
    if esses:
        return max(esses, key=lambda c: c.avg_speed_kph)
    return max(multi, key=lambda c: c.avg_speed_kph)


def _longest_run_m(pts: List[TelPoint], condition) -> float:
    """Longest contiguous run (metres) where condition(point) is True."""
    best = 0.0
    run  = 0.0
    for i in range(1, len(pts)):
        if condition(pts[i]):
            run += abs(pts[i].dist_m - pts[i-1].dist_m)
        else:
            best = max(best, run)
            run  = 0.0
    return max(best, run)


def _analyse_band(lap: RefLapFile, band_start: float, band_end: float) -> Optional[dict]:
    pts = [p for p in lap.trace.points if band_start <= p.dist_m <= band_end]
    if len(pts) < 10:
        return None

    # 1. Steering sign changes
    active_steer = [p.steer_pct for p in pts if abs(p.steer_pct) > 1.0]
    signs = [1 if s > 0 else -1 for s in active_steer]
    sign_changes = sum(1 for i in range(1, len(signs)) if signs[i] != signs[i-1])

    # 2. Steering RMS
    steer_rms = math.sqrt(sum(p.steer_pct**2 for p in pts) / len(pts)) if pts else 0.0

    # 3. Min steering magnitude
    min_steer = min(abs(p.steer_pct) for p in pts)

    # 4. Longest continuous <1% steer interval (metres)
    longest_reset_m = _longest_run_m(pts, lambda p: abs(p.steer_pct) < 1.0)

    # 5. Longest >85% throttle interval (metres)
    longest_throttle_m = _longest_run_m(pts, lambda p: p.throttle_pct > 85.0)

    # 6. Brake re-applications
    brake_reapps = sum(
        1 for i in range(1, len(pts))
        if pts[i-1].brake_pct < 5.0 and pts[i].brake_pct >= 5.0
    )

    # 7. Lateral load proxy
    lat_load = (sum(abs(p.steer_pct) * (p.speed_kph / 100.0) ** 2 for p in pts)
                / len(pts)) if pts else 0.0

    # 8. Steering active %
    steering_active_pct = 100.0 * sum(1 for p in pts if abs(p.steer_pct) > 5.0) / len(pts)

    return dict(
        sign_changes=sign_changes,
        steer_rms=steer_rms,
        min_steer=min_steer,
        longest_reset_m=longest_reset_m,
        longest_throttle_m=longest_throttle_m,
        brake_reapps=brake_reapps,
        lat_load=lat_load,
        steering_active_pct=steering_active_pct,
        n_pts=len(pts),
    )


def _flow_failure_reason(m: dict) -> Optional[str]:
    """Return the PRIMARY reason why this lap fails flow-zone criteria, or None."""
    # Order matters: check most common failure first
    if m['sign_changes'] < 2:
        return f"insufficient sign changes ({m['sign_changes']} < 2)"
    if m['steer_rms'] < 5.0:
        return f"steering RMS below threshold ({m['steer_rms']:.2f}% < 5.0%)"
    if m['longest_reset_m'] > 50.0:
        return f"reset gap detected ({m['longest_reset_m']:.0f}m of <1% steer)"
    if m['brake_reapps'] > 0:
        return f"brake re-application inside complex ({m['brake_reapps']} event(s))"
    return None   # passes all criteria


# ─────────────────────────────────────────────────────────────────────────────
# PART 3 helpers
# ─────────────────────────────────────────────────────────────────────────────

def _count_speed_minima(pts: List[TelPoint], min_separation_m: float = 60.0) -> List[float]:
    """Return list of dist_m for local speed minima in pts."""
    minima: List[float] = []
    for i in range(1, len(pts) - 1):
        if pts[i].speed_kph < pts[i-1].speed_kph and pts[i].speed_kph < pts[i+1].speed_kph:
            if not minima or pts[i].dist_m - minima[-1] > min_separation_m:
                minima.append(pts[i].dist_m)
    return minima


# ─────────────────────────────────────────────────────────────────────────────
# PART 4 helpers
# ─────────────────────────────────────────────────────────────────────────────

def _debug_reset(lap: RefLapFile, start_m: float, end_m: float) -> List[dict]:
    """
    Verbose replication of _detect_driver_reset — returns list of firing windows.
    Does NOT call the original function. Read-only.
    """
    pts = [p for p in lap.trace.points if start_m <= p.dist_m <= end_m]
    THROTTLE_WIN = 48   # ~0.8s @ 60 Hz
    STEER_WIN    = 30   # ~0.5s @ 60 Hz
    hits = []

    for i in range(len(pts) - THROTTLE_WIN + 1):
        window = pts[i:i + THROTTLE_WIN]
        throttle_ok = all(p.throttle_pct > 85.0 for p in window)
        brake_ok    = all(p.brake_pct == 0.0    for p in window)
        if not (throttle_ok and brake_ok):
            continue

        for j in range(len(window) - STEER_WIN + 1):
            sw  = window[j:j + STEER_WIN]
            rms = math.sqrt(sum(p.steer_pct ** 2 for p in sw) / STEER_WIN)
            if rms < 1.5:
                avg_thr   = sum(p.throttle_pct for p in sw) / STEER_WIN
                avg_brake = sum(p.brake_pct    for p in sw) / STEER_WIN
                hits.append(dict(
                    dist_start=sw[0].dist_m,
                    dist_end  =sw[-1].dist_m,
                    steer_rms =rms,
                    avg_throttle=avg_thr,
                    avg_brake   =avg_brake,
                ))
                break   # first hit in this throttle window is enough
        if hits and hits[-1]['dist_start'] >= pts[i].dist_m:
            break       # one report per lap is enough for diagnosis

    return hits


# ─────────────────────────────────────────────────────────────────────────────
# PART 1 — print
# ─────────────────────────────────────────────────────────────────────────────

def print_part1(laps: List[RefLapFile], st: dict, sets: dict,
                dirty_engine: CoachingEngine, clean_engine: CoachingEngine):
    W = 72
    print()
    print("═" * W)
    print("  PART 1 — REFERENCE LAP SANITY CHECK")
    print("═" * W)

    # Distribution
    print(f"\n  1.1  LAP TIME DISTRIBUTION  ({len(laps)} laps total)")
    print(f"       Mean       : {_fmt(st['mean'])}")
    print(f"       Median     : {_fmt(st['median'])}")
    print(f"       Std dev    : {st['std']:.3f}s")
    print(f"       5th  pct   : {_fmt(st['p5'])}")
    print(f"       25th pct   : {_fmt(st['p25'])}")
    print(f"       75th pct   : {_fmt(st['p75'])}")
    print(f"       95th pct   : {_fmt(st['p95'])}")
    print(f"       Outlier band: < {_fmt(st['lo_threshold'])} or > {_fmt(st['hi_threshold'])}")

    # Outliers
    outliers = [l for l in laps
                if l.lap_time < st['lo_threshold'] or l.lap_time > st['hi_threshold']]
    print(f"\n  1.2  OUTLIERS  ({len(outliers)} laps outside median ± 3σ)")
    for l in outliers[:20]:
        flag = " ← TARGET" if abs(l.lap_time - TARGET_LAP_S) < 0.5 else ""
        print(f"       {_fmt(l.lap_time)}  {l.car_name[:50]}{flag}")
    if len(outliers) > 20:
        print(f"       ... and {len(outliers)-20} more")

    is_outlier = any(abs(l.lap_time - TARGET_LAP_S) < 0.5 for l in outliers)
    within_1s  = sum(1 for l in laps if abs(l.lap_time - TARGET_LAP_S) <= 1.0)
    print(f"\n       Is {_fmt(TARGET_LAP_S)} an outlier? {'YES' if is_outlier else 'NO'}")
    print(f"       Laps within ±1s of {_fmt(TARGET_LAP_S)}: {within_1s}")

    # Fastest 5 plausibility
    print(f"\n  1.3  FASTEST 5 LAPS — PLAUSIBILITY CHECK")
    print(f"       {'Lap time':<12} {'Max spd':>8} {'Avg spd':>8} {'Verdict':<12} Car")
    for l in laps[:5]:
        mx, avg, verdict = _plausibility(l)
        print(f"       {_fmt(l.lap_time):<12} {mx:>7.1f}k {avg:>7.1f}k {verdict:<12} "
              f"{l.car_name[:40]}")

    # Filtered sets
    print(f"\n  1.4  FILTERED REFERENCE SETS")
    print(f"       Option A (p5–p25)        : {len(sets['A'])} laps  "
          f"[{_fmt(sets['A'][0].lap_time)} – {_fmt(sets['A'][-1].lap_time)}]"
          if sets['A'] else "       Option A: 0 laps")
    bc = sets['B']
    print(f"       Option B (k-means lower) : {len(bc)} laps  "
          f"[{_fmt(bc[0].lap_time)} – {_fmt(bc[-1].lap_time)}]"
          if bc else "       Option B: 0 laps")
    cc = sets['C']
    print(f"       Option C (≤ p25+1.5s)    : {len(cc)} laps  "
          f"[{_fmt(cc[0].lap_time)} – {_fmt(cc[-1].lap_time)}]  ← USED"
          if cc else "       Option C: 0 laps")

    # Engine comparison
    print(f"\n  1.5  ENGINE COMPARISON")
    print(f"       Dirty engine (50 fastest)   : "
          f"{len(dirty_engine.corners)} corners, {len(dirty_engine.complexes)} sections"
          f"  [{', '.join(cx.complex_type for cx in dirty_engine.complexes)}]")
    clean_types = ', '.join(cx.complex_type for cx in clean_engine.complexes) or 'none'
    print(f"       Clean engine (Option C ×50) : "
          f"{len(clean_engine.corners)} corners, {len(clean_engine.complexes)} sections"
          f"  [{clean_types}]")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# PART 2 — print
# ─────────────────────────────────────────────────────────────────────────────

def print_part2(cx: Optional[Complex], results: List[dict], laps: List[RefLapFile]):
    W = 72
    print("═" * W)
    print("  PART 2 — MAGGOTS–BECKETTS FLOW-ZONE FORENSIC")
    print("═" * W)

    if cx is None:
        print("  ✗  No multi-corner complex found in clean engine.")
        print()
        return

    band_start = cx.start_m - 50
    band_end   = cx.end_m   + 50
    print(f"\n  Section : [{cx.index}] {cx.name}")
    print(f"  Type    : {cx.complex_type}")
    print(f"  Corners : T{',T'.join(str(i) for i in cx.corner_indices)}")
    print(f"  Band    : {band_start:.0f}m → {band_end:.0f}m  ({band_end-band_start:.0f}m wide)")
    print(f"  Avg speed (engine): {cx.avg_speed_kph:.1f} kph")
    print(f"  Apex speeds: {[f'{c.apex_speed_kph:.0f}kph' for c in cx.corners]}")
    print(f"  Esses threshold: 150 kph (avg apex speed must exceed)")
    print()

    valid = [r for r in results if r is not None]
    N = len(valid)
    if N == 0:
        print("  ✗  No valid band data from any filtered lap.")
        print()
        return

    # Aggregate
    def mean_of(key):
        return sum(r[key] for r in valid) / N

    sign_ge3    = 100 * sum(1 for r in valid if r['sign_changes'] >= 3) / N
    sign_ge2    = 100 * sum(1 for r in valid if r['sign_changes'] >= 2) / N
    no_reset    = 100 * sum(1 for r in valid if r['longest_reset_m'] <= 50) / N
    rms_gt5     = 100 * sum(1 for r in valid if r['steer_rms'] > 5.0) / N
    no_brake    = 100 * sum(1 for r in valid if r['brake_reapps'] == 0) / N
    all_pass    = 100 * sum(
        1 for r in valid
        if r['sign_changes'] >= 2 and r['steer_rms'] > 5.0
        and r['longest_reset_m'] <= 50 and r['brake_reapps'] == 0
    ) / N

    print(f"  2.1  AGGREGATE STATS  ({N} filtered laps analysed)")
    print(f"       Mean sign changes           : {mean_of('sign_changes'):.1f}")
    print(f"       Mean steering RMS           : {mean_of('steer_rms'):.2f}%")
    print(f"       Mean longest reset gap      : {mean_of('longest_reset_m'):.1f}m")
    print(f"       Mean longest throttle run   : {mean_of('longest_throttle_m'):.1f}m")
    print(f"       Mean lateral load proxy     : {mean_of('lat_load'):.1f}")
    print(f"       Mean steering active %      : {mean_of('steering_active_pct'):.1f}%")
    print()
    print(f"       % laps with ≥ 3 sign changes   : {sign_ge3:.1f}%")
    print(f"       % laps with ≥ 2 sign changes   : {sign_ge2:.1f}%")
    print(f"       % laps with no reset > 50m     : {no_reset:.1f}%")
    print(f"       % laps with steer RMS > 5%     : {rms_gt5:.1f}%")
    print(f"       % laps with no brake re-app    : {no_brake:.1f}%")
    print(f"       % laps passing ALL flow criteria: {all_pass:.1f}%")
    print()

    # Per-lap failure summary
    failure_counts: Counter = Counter()
    for r in valid:
        reason = _flow_failure_reason(r)
        if reason:
            # Extract primary rule word
            if "sign change" in reason:
                failure_counts["insufficient sign changes"] += 1
            elif "RMS" in reason:
                failure_counts["steering RMS below threshold"] += 1
            elif "reset gap" in reason:
                failure_counts["reset detected"] += 1
            elif "brake" in reason:
                failure_counts["brake re-application"] += 1
        else:
            failure_counts["PASSES all criteria"] += 1

    print("  2.2  FAILURE REASON DISTRIBUTION")
    for reason, count in failure_counts.most_common():
        pct = 100 * count / N
        print(f"       {reason:<40}: {count:4d} laps ({pct:.1f}%)")
    print()

    # Sample failure detail — first 10 failing laps
    print("  2.3  SAMPLE PER-LAP DETAIL (first 10 failing laps)")
    printed = 0
    for lap, r in zip(laps, results):
        if r is None:
            continue
        reason = _flow_failure_reason(r)
        if reason is None:
            continue
        print(f"       {_fmt(lap.lap_time)}  sign_chg={r['sign_changes']}  "
              f"rms={r['steer_rms']:.2f}%  reset={r['longest_reset_m']:.0f}m  "
              f"brake_reapps={r['brake_reapps']}  → {reason}")
        printed += 1
        if printed >= 10:
            break
    print()


# ─────────────────────────────────────────────────────────────────────────────
# PART 3 — print
# ─────────────────────────────────────────────────────────────────────────────

def print_part3(cx: Optional[Complex], laps: List[RefLapFile]):
    W = 72
    print("═" * W)
    print("  PART 3 — CONSENSUS INSTABILITY CHECK")
    print("═" * W)
    print()

    if cx is None:
        print("  No complex available — skipping.")
        print()
        return

    band_start = cx.start_m - 50
    band_end   = cx.end_m   + 50

    all_minima: List[List[float]] = []
    count_dist: Counter = Counter()

    for lap in laps:
        pts = [p for p in lap.trace.points if band_start <= p.dist_m <= band_end]
        if len(pts) < 5:
            continue
        m = _count_speed_minima(pts)
        count_dist[len(m)] += 1
        all_minima.append(m)

    print(f"  Band: {band_start:.0f}m → {band_end:.0f}m")
    print(f"  Laps analysed: {len(all_minima)}")
    print()
    print("  3.1  SPEED MINIMA COUNT DISTRIBUTION")
    for count, freq in sorted(count_dist.items()):
        bar = "█" * min(freq, 40)
        print(f"       {count} minima: {freq:4d} laps  {bar}")
    print()

    # Apex variance per minimum position
    max_minima = max(count_dist.keys()) if count_dist else 0
    print("  3.2  APEX DISTANCE VARIANCE PER MINIMUM")
    print(f"       (stdev > 40m → UNSTABLE — consensus clustering will fragment)")
    print()
    for idx in range(max_minima):
        positions = [m[idx] for m in all_minima if len(m) > idx]
        if len(positions) < 5:
            print(f"       Minimum {idx+1}: too few laps ({len(positions)}) — skip")
            continue
        sd   = statistics.stdev(positions) if len(positions) > 1 else 0.0
        mean = statistics.mean(positions)
        flag = "  ← UNSTABLE" if sd > 40 else ""
        print(f"       Minimum {idx+1}: mean={mean:.0f}m  stdev={sd:.1f}m  n={len(positions)}{flag}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# PART 4 — print
# ─────────────────────────────────────────────────────────────────────────────

def print_part4(cx: Optional[Complex], laps: List[RefLapFile]):
    W = 72
    print("═" * W)
    print("  PART 4 — RESET LOGIC DEBUG")
    print("═" * W)
    print()

    if cx is None:
        print("  No complex available — skipping.")
        print()
        return

    band_start = cx.start_m
    band_end   = cx.end_m

    print(f"  Band: {band_start:.0f}m → {band_end:.0f}m")
    print(f"  Reset criteria: throttle>85% for 48pts AND steer_rms<1.5% for 30pts AND brake=0")
    print()

    fire_laps  = 0
    total_laps = 0
    sample_hits: List[dict] = []   # collect first 5 distinct reset events

    for lap in laps:
        total_laps += 1
        hits = _debug_reset(lap, band_start, band_end)
        if hits:
            fire_laps += 1
            if len(sample_hits) < 5:
                for h in hits[:1]:
                    sample_hits.append(dict(
                        lap_time=lap.lap_time,
                        car=lap.car_name[:40],
                        **h
                    ))

    print(f"  4.1  SUMMARY")
    print(f"       Laps analysed     : {total_laps}")
    print(f"       Laps with reset   : {fire_laps} ({100*fire_laps/max(total_laps,1):.1f}%)")
    print(f"       Laps without reset: {total_laps - fire_laps}"
          f" ({100*(total_laps-fire_laps)/max(total_laps,1):.1f}%)")
    print()

    if sample_hits:
        print("  4.2  SAMPLE RESET EVENTS (first 5 laps that fire)")
        for h in sample_hits:
            print(f"       {_fmt(h['lap_time'])}  @{h['dist_start']:.0f}m–{h['dist_end']:.0f}m  "
                  f"throttle={h['avg_throttle']:.0f}%  "
                  f"steer_rms={h['steer_rms']:.2f}%  "
                  f"brake={h['avg_brake']:.1f}%")
            print(f"               {h['car']}")
    else:
        print("  4.2  No reset events found inside band.")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# PART 5 — print
# ─────────────────────────────────────────────────────────────────────────────

def print_part5(
    laps: List[RefLapFile],
    st: dict,
    sets: dict,
    dirty_engine: CoachingEngine,
    clean_engine: CoachingEngine,
    cx: Optional[Complex],
    band_results: List[Optional[dict]],
    reset_fire_count: int,
    reset_total: int,
    apex_variances: List[Tuple[int, float]],   # (min_idx, stdev)
):
    W = 72
    print("═" * W)
    print("  PART 5 — FINAL DIAGNOSTIC")
    print("═" * W)
    print()

    is_outlier = any(abs(l.lap_time - TARGET_LAP_S) < 0.5
                     for l in laps
                     if l.lap_time < st['lo_threshold'])
    within_1s  = sum(1 for l in laps if abs(l.lap_time - TARGET_LAP_S) <= 1.0)
    opt_c_count = len(sets['C'])

    valid_results = [r for r in band_results if r is not None]
    N = len(valid_results)

    if N > 0:
        sign_ge3_pct = 100 * sum(1 for r in valid_results if r['sign_changes'] >= 3) / N
        no_reset_pct = 100 * sum(1 for r in valid_results if r['longest_reset_m'] <= 50) / N
        rms_gt5_pct  = 100 * sum(1 for r in valid_results if r['steer_rms'] > 5.0) / N
        all_pass_pct = 100 * sum(
            1 for r in valid_results
            if r['sign_changes'] >= 2 and r['steer_rms'] > 5.0
            and r['longest_reset_m'] <= 50 and r['brake_reapps'] == 0
        ) / N
        mean_sign    = sum(r['sign_changes'] for r in valid_results) / N
        mean_rms     = sum(r['steer_rms']    for r in valid_results) / N
    else:
        sign_ge3_pct = no_reset_pct = rms_gt5_pct = all_pass_pct = 0.0
        mean_sign = mean_rms = 0.0

    # Determine primary failure reason
    if N > 0:
        fail_counter: Counter = Counter()
        for r in valid_results:
            reason = _flow_failure_reason(r)
            if reason:
                if "sign change" in reason:    fail_counter["sign_change_threshold"] += 1
                elif "RMS"       in reason:    fail_counter["RMS_threshold"]         += 1
                elif "reset"     in reason:    fail_counter["reset_logic"]           += 1
                elif "brake"     in reason:    fail_counter["brake_reapplication"]   += 1
        primary_block = fail_counter.most_common(1)[0][0] if fail_counter else "none_detected"
    else:
        primary_block = "no_data"

    # Apex variance check
    worst_apex_var = max((v for _, v in apex_variances), default=0.0)
    consensus_unstable = worst_apex_var > 40.0

    print("  ┌─────────────────────────────────────────────────────────────────")
    print(f"  │ 1.  Is reference lap set valid?")
    outlier_count = sum(1 for l in laps
                        if l.lap_time < st['lo_threshold'] or l.lap_time > st['hi_threshold'])
    print(f"  │     Outlier count: {outlier_count} laps outside median ± 3σ")
    print(f"  │     {_fmt(TARGET_LAP_S)} is {'AN OUTLIER' if is_outlier else 'NOT an outlier'}")
    print(f"  │     Laps within ±1s of {_fmt(TARGET_LAP_S)}: {within_1s}")
    verdict = "CONTAMINATED" if is_outlier or outlier_count > 0 else "CLEAN"
    print(f"  │     Verdict: {verdict}")
    print("  │")
    print(f"  │ 2.  Is {_fmt(TARGET_LAP_S)} a statistical outlier?")
    print(f"  │     Threshold: median={_fmt(st['median'])} ± 3σ={st['std']*3:.2f}s")
    print(f"  │     Range: {_fmt(st['lo_threshold'])} – {_fmt(st['hi_threshold'])}")
    print(f"  │     {_fmt(TARGET_LAP_S)} is {'BELOW' if TARGET_LAP_S < st['lo_threshold'] else 'WITHIN'} threshold")
    print(f"  │     Answer: {'YES' if is_outlier else 'NO'}")
    print("  │")
    print(f"  │ 3.  After filtering (Option C: p25 + 1.5s), how many laps remain?")
    print(f"  │     Total: {len(laps)}   Filtered: {opt_c_count}   Used for clean engine: {min(opt_c_count, MAX_REF_LAPS)}")
    clean_corners  = len(clean_engine.corners)
    clean_cx_types = [cx_.complex_type for cx_ in clean_engine.complexes] if clean_engine.complexes else []
    print(f"  │     Clean engine result: {clean_corners} corners, {len(clean_engine.complexes)} sections {clean_cx_types}")
    print("  │")
    print(f"  │ 4.  Does Maggots-Becketts satisfy flow criteria in majority of laps?")
    print(f"  │     Sign changes ≥ 3:         {sign_ge3_pct:.1f}% of laps")
    print(f"  │     No reset detected:         {no_reset_pct:.1f}% of laps")
    print(f"  │     Steer RMS > 5.0%:          {rms_gt5_pct:.1f}% of laps")
    majority_pass = all_pass_pct >= 60.0
    print(f"  │     Majority satisfying all:  {'YES' if majority_pass else 'NO'}  ({all_pass_pct:.1f}%)")
    print("  │")
    print(f"  │ 5.  Which rule blocks flow-zone / esses classification?")
    print(f"  │     Primary block: {primary_block}")
    print(f"  │     Evidence: mean sign_changes={mean_sign:.1f}, mean steer_rms={mean_rms:.2f}%")
    if cx:
        apex_speeds = [c.apex_speed_kph for c in cx.corners]
        avg_apex = sum(apex_speeds)/len(apex_speeds) if apex_speeds else 0
        print(f"  │     Apex speeds in complex: {[f'{s:.0f}kph' for s in apex_speeds]}")
        print(f"  │     Avg apex speed: {avg_apex:.1f} kph  (esses threshold: 150 kph)")
        print(f"  │     → Complex typed as '{cx.complex_type}' "
              f"{'(CORRECT)' if avg_apex > 150 else '(TOO LOW — classified linked)'}")
    print("  │")
    print(f"  │ 6.  Is failure due to:")
    reset_pct = 100 * reset_fire_count / max(reset_total, 1)
    print(f"  │     reset logic:           {'YES' if reset_fire_count > 0 else 'NO '} — "
          f"fires in {reset_fire_count}/{reset_total} laps ({reset_pct:.1f}%) "
          f"inside band")
    rms_fail = mean_rms < 5.0 and N > 0
    print(f"  │     RMS threshold:         {'YES' if rms_fail else 'NO '} — "
          f"mean steer_rms={mean_rms:.2f}% (threshold 5.0%)")
    sign_fail = mean_sign < 2.0 and N > 0
    print(f"  │     sign change threshold: {'YES' if sign_fail else 'NO '} — "
          f"mean sign_changes={mean_sign:.1f} (need ≥ 2)")
    print(f"  │     consensus instability: {'YES' if consensus_unstable else 'NO '} — "
          f"worst apex stdev={worst_apex_var:.1f}m (threshold 40m)")
    dirty_c = len(dirty_engine.corners)
    print(f"  │     reference contamination: {'YES' if dirty_c < clean_corners else 'NO '} — "
          f"dirty={dirty_c} corners, clean={clean_corners} corners")
    print("  └─────────────────────────────────────────────────────────────────")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print()
    print("═" * 72)
    print("  SENNA AI — Silverstone Forensic Diagnostic")
    print("  Telemetry truth extraction  |  Read-only")
    print("═" * 72)

    # ── Load ───────────────────────────────────────────────────────────────
    print(f"\n  Loading: {SILVERSTONE_FOLDER}")
    laps, errors = scan_lap_files(SILVERSTONE_FOLDER)
    if errors:
        print(f"  ⚠  {len(errors)} load error(s)")
    if not laps:
        print("  ✗  No laps loaded.")
        sys.exit(1)

    laps_sorted = sorted(laps, key=lambda l: l.lap_time)
    print(f"  ✓  {len(laps_sorted)} laps loaded")

    # ── Stats + filter ────────────────────────────────────────────────────
    print("  Computing statistics…")
    st   = _lap_stats(laps_sorted)
    sets = _filtered_sets(laps_sorted, st)
    print(f"  Option C: {len(sets['C'])} laps (≤ p25+1.5s = {_fmt(st['p25']+1.5)})")

    # ── Dirty engine (first 50 fastest) ──────────────────────────────────
    print("  Building dirty engine (50 fastest laps)…")
    dirty_engine = _build_engine(laps_sorted[:MAX_REF_LAPS])
    print(f"  Dirty: {len(dirty_engine.corners)} corners, {len(dirty_engine.complexes)} sections")

    # ── Clean engine (Option C) ───────────────────────────────────────────
    clean_ref = sorted(sets['C'], key=lambda l: l.lap_time)[:MAX_REF_LAPS]
    print(f"  Building clean engine ({len(clean_ref)} laps from Option C)…")
    clean_engine = _build_engine(clean_ref)
    print(f"  Clean: {len(clean_engine.corners)} corners, {len(clean_engine.complexes)} sections")

    # ── Identify Maggots band ────────────────────────────────────────────
    cx = _find_maggots_cx(clean_engine)
    if cx:
        band_start = cx.start_m - 50
        band_end   = cx.end_m   + 50
        print(f"  Maggots band: {band_start:.0f}m → {band_end:.0f}m  [{cx.name}]")
    else:
        band_start = band_end = 0.0
        print("  ⚠  No multi-corner complex found in clean engine")

    # ── Band analysis (Parts 2–4) ─────────────────────────────────────────
    opt_c_laps = sorted(sets['C'], key=lambda l: l.lap_time)

    print(f"  Analysing {len(opt_c_laps)} filtered laps through band…")
    band_results = [_analyse_band(l, band_start, band_end) for l in opt_c_laps]

    # Reset count for Part 5 summary
    reset_fire_count = 0
    reset_total      = len(opt_c_laps)
    for lap in opt_c_laps:
        if cx and _debug_reset(lap, cx.start_m, cx.end_m):
            reset_fire_count += 1

    # Apex variance for Part 5
    apex_variances: List[Tuple[int, float]] = []
    if cx:
        all_minima = []
        for lap in opt_c_laps:
            pts = [p for p in lap.trace.points if band_start <= p.dist_m <= band_end]
            if len(pts) >= 5:
                all_minima.append(_count_speed_minima(pts))
        max_m = max((len(m) for m in all_minima), default=0)
        for idx in range(max_m):
            positions = [m[idx] for m in all_minima if len(m) > idx]
            if len(positions) > 1:
                apex_variances.append((idx, statistics.stdev(positions)))

    # ── Print all parts ───────────────────────────────────────────────────
    print_part1(laps_sorted, st, sets, dirty_engine, clean_engine)
    print_part2(cx, band_results, opt_c_laps)
    print_part3(cx, opt_c_laps)
    print_part4(cx, opt_c_laps)
    print_part5(
        laps_sorted, st, sets,
        dirty_engine, clean_engine,
        cx, band_results,
        reset_fire_count, reset_total,
        apex_variances,
    )


if __name__ == "__main__":
    main()
