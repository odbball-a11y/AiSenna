# -*- coding: utf-8 -*-
# Corner detection and track data structures
from senna_ai.telemetry.models import TelPoint, LapTrace
from senna_ai.coaching.coaching_constants import (
    BRAKE_THRESHOLD, MIN_ZONE_GAP_M, APPROACH_WARN_M,
)
from dataclasses import dataclass, field
from typing import Optional
import os
import math
import logging

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class Corner:
    """A detected corner / braking zone on the track."""
    index: int                   # 1-based corner number
    brake_point_m: float         # distance where braking starts
    brake_speed_kph: float       # speed at brake point
    apex_m: float                # distance at minimum speed
    apex_speed_kph: float        # minimum speed
    apex_gear: int
    exit_m: float                # distance where throttle resumes
    exit_speed_kph: float
    max_brake_pct: float         # peak brake pressure in zone
    approach_m: float            # distance where we give the voice cue
    archetype: str = ""          # hairpin, medium_speed, high_speed_flow, heavy_brake


@dataclass
class Sector:
    """A sector = brake point of this corner -> brake point of next corner."""
    index: int
    corner: Corner
    start_m: float
    end_m: float
    length_m: float
    wraps: bool = False


@dataclass
class SectorResult:
    """Live analysis result for a single sector pass."""
    sector_idx: int
    time: float = 0.0
    delta_to_target: float = 0.0
    delta_to_pb: float = 0.0
    brake_grade: str = ""
    pressure_grade: str = ""
    turn_in_grade: str = ""
    apex_grade: str = ""
    exit_grade: str = ""
    line_grade: str = ""

    def overall_grade(self) -> str:
        """Return overall colour: green/yellow/red based on grades."""
        grades = [g for g in [self.brake_grade, self.pressure_grade,
                              self.turn_in_grade, self.apex_grade,
                              self.exit_grade, self.line_grade] if g]
        if not grades:
            return ""
        poor_count = sum(1 for g in grades if g == "poor")
        good_count = sum(1 for g in grades if g == "good")
        if poor_count >= 2:
            return "poor"
        if good_count >= len(grades) * 0.6:
            return "good"
        return "ok"


@dataclass
class CornerTarget:
    """Progressive target for a single corner — the heart of adaptive coaching."""
    corner: Corner
    tier: int = 0
    consecutive_beats: int = 0
    target_trace: Optional[LapTrace] = None
    target_label: str = ""
    available_traces: list[LapTrace] = field(default_factory=list)
    available_times: list[float] = field(default_factory=list)
    player_best_apex_speed: float = 0.0
    player_best_trace: Optional[LapTrace] = None
    target_brake_m: float = 0.0
    target_apex_speed: float = 0.0
    target_exit_speed: float = 0.0


def detect_corners(points: list[TelPoint]) -> list[Corner]:
    """
    Detect corners from telemetry using multiple signals:
      1. Braking zones  (brake > threshold)
      2. Steering zones (|steer| > threshold with deceleration)
      3. Speed drops    (significant deceleration regardless of inputs)
    """
    if len(points) < 50:
        return []

    window = max(5, len(points) // 200)
    speeds = [p.speed_kph for p in points]

    smooth_speeds = []
    for i in range(len(speeds)):
        lo = max(0, i - window)
        hi = min(len(speeds), i + window + 1)
        smooth_speeds.append(sum(speeds[lo:hi]) / (hi - lo))

    BRAKE_THRESH = 8.0
    STEER_THRESH = 8.0
    SPEED_DROP_THRESH = 25
    THROTTLE_EXIT_THRESH = 40.0

    events = []
    in_event = False
    event = {}
    recent_max_speed = 0.0

    for i, p in enumerate(points):
        recent_max_speed = max(recent_max_speed, p.speed_kph)
        is_braking = p.brake_pct > BRAKE_THRESH
        
        # Adaptive steering threshold based on speed
        if p.speed_kph > 150:
            steer_thresh = 3.0
        elif p.speed_kph > 100:
            steer_thresh = 5.0
        else:
            steer_thresh = STEER_THRESH
        
        is_turning = abs(p.steer_pct) > steer_thresh
        is_decelerating = (recent_max_speed - p.speed_kph) > SPEED_DROP_THRESH

        if not in_event and (is_braking or (is_turning and is_decelerating)):
            in_event = True
            event = {
                "start_m": p.dist_m, "start_speed": p.speed_kph,
                "min_speed": p.speed_kph, "min_speed_dist": p.dist_m,
                "max_brake": p.brake_pct, "max_steer": abs(p.steer_pct),
                "gear_at_min": p.gear, "end_m": p.dist_m, "end_speed": p.speed_kph,
            }
        elif in_event:
            if p.speed_kph < event["min_speed"]:
                event["min_speed"] = p.speed_kph
                event["min_speed_dist"] = p.dist_m
                event["gear_at_min"] = p.gear
            event["max_brake"] = max(event["max_brake"], p.brake_pct)
            event["max_steer"] = max(event["max_steer"], abs(p.steer_pct))

            on_throttle = p.throttle_pct > THROTTLE_EXIT_THRESH
            off_brake = p.brake_pct < 5
            straightening = abs(p.steer_pct) < steer_thresh
            speeding_up = p.speed_kph > event["min_speed"] + 10

            # NEW: Also end event if brake drops AND we're not turning much
            # This prevents merging separate corners
            brake_dropped = p.brake_pct < 5 and event["max_brake"] > 20
            not_turning = abs(p.steer_pct) < steer_thresh * 0.5  # 50% of threshold

            if (on_throttle and off_brake and (straightening or speeding_up)) or (brake_dropped and not_turning):
                event["end_m"] = p.dist_m
                event["end_speed"] = p.speed_kph
                events.append(event)
                in_event = False
                recent_max_speed = p.speed_kph

    if not events:
        return []

    significant = [e for e in events
                   if e["start_speed"] - e["min_speed"] > 15 and e["end_m"] - e["start_m"] > 20]

    if not significant:
        return []

    # NEW: Detect multiple apexes within long steering zones with minimal braking
    split_events = []
    for event in significant:
        zone_length = event["end_m"] - event["start_m"]
        max_brake = event["max_brake"]
        
        # Check if this is a long steering zone with minimal braking
        if zone_length > 200 and max_brake < 20:  # Minimal braking (<20%)
            # Extract steering magnitude signal within this zone
            zone_points = [p for p in points 
                          if event["start_m"] <= p.dist_m <= event["end_m"]]
            
            if len(zone_points) >= 10:
                steering_mag = [abs(p.steer_pct) for p in zone_points]
                distances = [p.dist_m for p in zone_points]
                
                # Find local peaks in steering magnitude
                peaks = []
                for j in range(1, len(steering_mag) - 1):
                    # Use adaptive threshold for peak detection based on speed at this point
                    if zone_points[j].speed_kph > 150:
                        peak_thresh = 3.0 * 0.6
                    elif zone_points[j].speed_kph > 100:
                        peak_thresh = 5.0 * 0.6
                    else:
                        peak_thresh = STEER_THRESH * 0.6
                    
                    if (steering_mag[j] > steering_mag[j-1] and 
                        steering_mag[j] > steering_mag[j+1] and
                        steering_mag[j] > peak_thresh):
                        peaks.append((distances[j], steering_mag[j]))
                
                # Filter peaks: need at least 80m separation
                filtered_peaks = []
                if peaks:
                    filtered_peaks.append(peaks[0])  # Keep first peak
                    for dist, mag in peaks[1:]:
                        if dist - filtered_peaks[-1][0] >= 80:
                            filtered_peaks.append((dist, mag))
                
                # If we found multiple distinct peaks, split the event
                if len(filtered_peaks) >= 2:
                    log.debug("Splitting long steering zone (%.0fm, brake=%.0f%%) into %d apexes",
                             zone_length, max_brake, len(filtered_peaks))
                    
                    # Create sub-events for each peak
                    for peak_idx, (peak_dist, peak_mag) in enumerate(filtered_peaks):
                        # Find speed at this peak distance
                        peak_point = None
                        for p in zone_points:
                            if abs(p.dist_m - peak_dist) < 5:
                                peak_point = p
                                break
                        
                        if peak_point:
                            # Determine start and end for this sub-corner
                            # Start: either zone start or midpoint between peaks
                            if peak_idx == 0:
                                sub_start = event["start_m"]
                            else:
                                prev_peak = filtered_peaks[peak_idx-1][0]
                                sub_start = (prev_peak + peak_dist) / 2
                            
                            # End: either zone end or midpoint between peaks
                            if peak_idx == len(filtered_peaks) - 1:
                                sub_end = event["end_m"]
                            else:
                                next_peak = filtered_peaks[peak_idx+1][0]
                                sub_end = (peak_dist + next_peak) / 2
                            
                            # Find min speed in this sub-range
                            sub_points = [p for p in zone_points 
                                         if sub_start <= p.dist_m <= sub_end]
                            if sub_points:
                                min_speed_pt = min(sub_points, key=lambda p: p.speed_kph)
                                
                                sub_event = {
                                    "start_m": sub_start,
                                    "start_speed": next((p.speed_kph for p in zone_points 
                                                         if p.dist_m >= sub_start), event["start_speed"]),
                                    "min_speed": min_speed_pt.speed_kph,
                                    "min_speed_dist": min_speed_pt.dist_m,
                                    "max_brake": max_brake,  # Use original max brake
                                    "max_steer": peak_mag,   # Use peak steering at this apex
                                    "gear_at_min": min_speed_pt.gear,
                                    "end_m": sub_end,
                                    "end_speed": next((p.speed_kph for p in zone_points 
                                                       if p.dist_m <= sub_end), event["end_speed"]),
                                }
                                split_events.append(sub_event)
                    continue  # Skip adding original event
        
        # Keep original event if not split
        split_events.append(event)
    
    # Use split events instead of original significant events
    merged = [split_events[0]]
    for z in split_events[1:]:
        if z["start_m"] - merged[-1]["end_m"] < MIN_ZONE_GAP_M:
            prev = merged[-1]
            prev["end_m"] = z["end_m"]
            prev["end_speed"] = z["end_speed"]
            if z["min_speed"] < prev["min_speed"]:
                prev["min_speed"] = z["min_speed"]
                prev["min_speed_dist"] = z["min_speed_dist"]
                prev["gear_at_min"] = z["gear_at_min"]
            prev["max_brake"] = max(prev["max_brake"], z["max_brake"])
            prev["max_steer"] = max(prev["max_steer"], z["max_steer"])
        else:
            merged.append(z)

    corners = []
    for i, z in enumerate(merged):
        brake_point_m = z["start_m"]
        for p in reversed(points):
            if p.dist_m >= z["start_m"]:
                continue
            if p.dist_m < z["start_m"] - 200:
                break
            if p.brake_pct > BRAKE_THRESH:
                brake_point_m = p.dist_m
            elif p.brake_pct < 2:
                break

        corners.append(Corner(
            index=i + 1,
            brake_point_m=brake_point_m,
            brake_speed_kph=z["start_speed"],
            apex_m=z["min_speed_dist"],
            apex_speed_kph=z["min_speed"],
            apex_gear=z["gear_at_min"],
            exit_m=z["end_m"],
            exit_speed_kph=z["end_speed"],
            max_brake_pct=z["max_brake"],
            approach_m=brake_point_m - APPROACH_WARN_M,
        ))
        log.info(
            "  C%d: brake@%.0fm -> apex@%.0fm (%.0fkph G%d) -> exit@%.0fm",
            i + 1, brake_point_m, z["min_speed_dist"], z["min_speed"],
            z["gear_at_min"], z["end_m"],
        )

    return corners


def build_sectors(corners: list[Corner], track_length: float = 0) -> list[Sector]:
    """Build sectors from corners: each sector = brake point -> next brake point."""
    if not corners:
        return []

    sectors = []
    for i, corner in enumerate(corners):
        if i < len(corners) - 1:
            next_brake = corners[i + 1].brake_point_m
            length = next_brake - corner.brake_point_m
            sectors.append(Sector(
                index=corner.index, corner=corner,
                start_m=corner.brake_point_m, end_m=next_brake,
                length_m=length, wraps=False,
            ))
        else:
            if track_length > 0:
                remaining = track_length - corner.brake_point_m
                first_brake = corners[0].brake_point_m
                length = remaining + first_brake
                sectors.append(Sector(
                    index=corner.index, corner=corner,
                    start_m=corner.brake_point_m,
                    end_m=corners[0].brake_point_m,
                    length_m=length, wraps=True,
                ))
            else:
                sectors.append(Sector(
                    index=corner.index, corner=corner,
                    start_m=corner.brake_point_m,
                    end_m=corner.exit_m + 200,
                    length_m=(corner.exit_m + 200) - corner.brake_point_m,
                ))

    for s in sectors:
        log.info("  S%d: %.0fm -> %.0fm (%.0fm)%s",
                 s.index, s.start_m, s.end_m, s.length_m,
                 " [wraps]" if s.wraps else "")

    return sectors


# ═══════════════════════════════════════════════════════════════════════════
# Consensus Corner Detection — stable corner map from multiple laps
# ═══════════════════════════════════════════════════════════════════════════

def build_consensus_corners(
    all_lap_corners: list[list[Corner]],
    min_vote_pct: float = 0.4,
    cluster_radius_m: float = 120.0,
    lap_max_speed_kph: float = 0.0,
) -> list[Corner]:
    """
    Build a single authoritative corner list from per-lap detections.

    1. Pool every detected apex from every lap.
    2. Cluster apex positions within `cluster_radius_m`.
    3. Keep clusters that appear in >= `min_vote_pct` of laps.
    4. Build a canonical Corner per cluster using median values.

    Returns corners numbered 1..N in track order.
    """
    import statistics as stat

    n_laps = len(all_lap_corners)
    if n_laps == 0:
        return []

    # ── 1. Pool all detected corners ──
    # Tag each with its source lap index
    tagged: list[tuple[int, Corner]] = []
    for lap_idx, corners in enumerate(all_lap_corners):
        for c in corners:
            tagged.append((lap_idx, c))

    if not tagged:
        return []

    # Sort by apex position
    tagged.sort(key=lambda t: t[1].apex_m)

    # ── 2. Cluster by apex proximity ──
    clusters: list[list[tuple[int, Corner]]] = []
    current_cluster: list[tuple[int, Corner]] = [tagged[0]]

    for i in range(1, len(tagged)):
        _, prev_c = current_cluster[-1]
        _, this_c = tagged[i]

        if this_c.apex_m - prev_c.apex_m <= cluster_radius_m:
            current_cluster.append(tagged[i])
        else:
            clusters.append(current_cluster)
            current_cluster = [tagged[i]]

    clusters.append(current_cluster)

    # ── 3. Filter by vote threshold ──
    min_votes = max(1, int(n_laps * min_vote_pct))
    consensus_corners: list[Corner] = []

    for cluster in clusters:
        # Count unique laps that contribute to this cluster
        contributing_laps = set(lap_idx for lap_idx, _ in cluster)
        if len(contributing_laps) < min_votes:
            continue

        corners_in = [c for _, c in cluster]

        # ── 4. Build canonical corner from median values ──
        brake_points = sorted(c.brake_point_m for c in corners_in)
        brake_speeds = sorted(c.brake_speed_kph for c in corners_in)
        apex_ms = sorted(c.apex_m for c in corners_in)
        apex_speeds = sorted(c.apex_speed_kph for c in corners_in)
        apex_gears = sorted(c.apex_gear for c in corners_in)
        exit_ms = sorted(c.exit_m for c in corners_in)
        exit_speeds = sorted(c.exit_speed_kph for c in corners_in)
        max_brakes = sorted(c.max_brake_pct for c in corners_in)

        median_brake_m = stat.median(brake_points)
        median_apex_m = stat.median(apex_ms)

        consensus_corners.append(Corner(
            index=0,  # renumbered below
            brake_point_m=median_brake_m,
            brake_speed_kph=stat.median(brake_speeds),
            apex_m=median_apex_m,
            apex_speed_kph=stat.median(apex_speeds),
            apex_gear=int(stat.median(apex_gears)),
            exit_m=stat.median(exit_ms),
            exit_speed_kph=stat.median(exit_speeds),
            max_brake_pct=stat.median(max_brakes),
            approach_m=median_brake_m - APPROACH_WARN_M,
        ))

    # ── 5. Sort and renumber ──
    consensus_corners.sort(key=lambda c: c.apex_m)
    for i, c in enumerate(consensus_corners):
        c.index = i + 1

    log.info(
        "Consensus corners: %d clusters from %d laps (%d detections, vote≥%d)",
        len(consensus_corners), n_laps,
        len(tagged), min_votes,
    )
    for c in consensus_corners:
        log.info(
            "  C%d: brake@%.0fm -> apex@%.0fm (%.0fkph G%d) -> exit@%.0fm",
            c.index, c.brake_point_m, c.apex_m,
            c.apex_speed_kph, c.apex_gear, c.exit_m,
        )

    # Classify corner archetypes
    classify_corner_archetypes(consensus_corners, lap_max_speed_kph)
    
    return consensus_corners


def classify_corner_archetypes(corners: list[Corner], lap_max_speed_kph: float) -> None:
    """
    Classify corners into archetypes based on speed ratio and braking characteristics.
    
    Archetypes:
    - hairpin: speed_ratio < 0.35
    - medium_speed: 0.35–0.65
    - high_speed_flow: speed_ratio > 0.65 AND max_brake_pct < 20%
    - heavy_brake: max_brake_pct > 40% (applies regardless of speed ratio)
    
    Note: heavy_brake takes precedence over other classifications.
    """
    for corner in corners:
        # Calculate speed ratio relative to lap maximum speed
        speed_ratio = corner.apex_speed_kph / lap_max_speed_kph if lap_max_speed_kph > 0 else 0
        
        # Apply classification rules
        if corner.max_brake_pct > 40:
            corner.archetype = "heavy_brake"
        elif speed_ratio < 0.35:
            corner.archetype = "hairpin"
        elif speed_ratio > 0.65 and corner.max_brake_pct < 20:
            corner.archetype = "high_speed_flow"
        else:
            corner.archetype = "medium_speed"
        
        log.debug("C%d classified as %s (ratio=%.2f, apex=%.0fkph, brake=%.0f%%)",
                 corner.index, corner.archetype, speed_ratio,
                 corner.apex_speed_kph, corner.max_brake_pct)
