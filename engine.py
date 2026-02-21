from __future__ import annotations
from senna_ai.track.corner_detection import Corner, Sector, SectorResult, CornerTarget
from senna_ai.track.composite_builder import CompositeLap
from senna_ai.track.complex_detection import Complex, detect_complexes
from senna_ai.track.force_stage_model import ForceStageModel
from senna_ai.track.track_model import TrackModel
from senna_ai.track.corner_detection import build_sectors

from senna_ai.telemetry.models import TelPoint, LapTrace, RefLapFile
from senna_ai.coaching.coaching_constants import *
from senna_ai.coaching.coaching_constants import MIN_SPEED_MPS
from senna_ai.coaching.coaching_constants import BRAKE_THRESHOLD
from senna_ai.coaching.coaching_constants import TIER_PROMOTION_LAPS
from senna_ai.infra.tts_engine import Speaker

import time
import logging
import random
from typing import List, Optional, Dict, Tuple

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Coaching Engine — Adaptive per-corner coaching with progressive targets
# ═══════════════════════════════════════════════════════════════════════════
class CoachingEngine:
    PHASE_WAITING = "waiting"
    PHASE_COACHING = "coaching"

    def __init__(self, speaker: Speaker, on_state_change=None):
        self.speaker = speaker
        self.on_state_change = on_state_change

        self.phase = self.PHASE_WAITING
        self.ref_laps: list[RefLapFile] = []
        self.composite: Optional[CompositeLap] = None
        self.track_model: Optional[TrackModel] = None
        self.force_model: ForceStageModel = ForceStageModel()
        self.complexes: list[Complex] = []
        self.complex_map: dict[int, Complex] = {}  # ADDED
        self.corners: list[Corner] = []
        self.sectors: list[Sector] = []

        # Live state
        self.live_speed = 0.0
        self.live_throttle = 0.0
        self.live_brake = 0.0
        self.live_gear = 0
        self.live_dist = 0.0
        self.live_x = 0.0
        self.live_z = 0.0
        self.current_track = ""
        self.current_car = ""
        self.current_car_class = ""
        self.current_corner_label = ""
        self.lap_count = 0

        # Per-corner tracking
        self._corner_ready: set[int] = set()
        self._corner_data: dict[int, list[TelPoint]] = {}
        self._approach_fired: set[int] = set()
        self._post_fired: set[int] = set()
        self._all_points: list[TelPoint] = []
        self._last_dist = 0.0
        self._inside_corner: Optional[int] = None

        # Lap timing
        self._lap_start_time: float = 0.0
        self.last_lap_time: float = 0.0
        self.best_lap_time: float = 0.0
        self.all_lap_times: list[float] = []

        # Sector timing & analysis
        self._current_sector_idx: int = -1
        self._sector_enter_time: float = 0.0
        self.sector_results: list[SectorResult] = []
        self.sector_pb: dict[int, float] = {}
        self.sector_target: dict[int, float] = {}
        self.last_sector_results: list[SectorResult] = []

        # Per-corner issue history for progressive feedback escalation
        self._issue_history: dict[tuple[int, str], int] = {}
        self._last_feedback: dict[int, str] = {}
        
        # ADDED: Enhanced coaching
        self.enhanced_coach = EnhancedCoachingGenerator()

    def set_reference_laps(self, laps: list[RefLapFile]):
        """Set ALL reference laps for the current track. Builds composite."""
        self.ref_laps = laps
        if not laps:
            return

        viable = [l for l in laps if l.corners and len(l.corners) >= 3
                  and l.lap_time > 0 and len(l.trace.points) >= 100]
        if not viable:
            viable = [l for l in laps if l.corners and l.lap_time > 0]
        if not viable:
            log.warning("No reference laps have detected corners — cannot build composite.")
            return

        max_corners = max(len(l.corners) for l in viable)
        min_acceptable = max(3, int(max_corners * 0.8))
        geometry_candidates = [l for l in viable if len(l.corners) >= min_acceptable]
        if not geometry_candidates:
            geometry_candidates = viable
        fastest = min(geometry_candidates, key=lambda l: l.lap_time)

        log.info("Geometry ref: %s (%.3fs, %d corners) — max_corners=%d across %d viable laps",
                 fastest.car_name[:30], fastest.lap_time, len(fastest.corners),
                 max_corners, len(viable))
        self.corners = fastest.corners

        track_len = fastest.track_length if fastest.track_length > 0 else 0
        self.sectors = build_sectors(self.corners, track_len)

        self.composite = CompositeLap(self.corners, laps)

        self.track_model = TrackModel(self.corners, self.sectors, laps, track_len)

        ref_traces = [l.trace for l in laps[:10]]
        self.complexes = detect_complexes(self.corners, ref_traces)
        self.complex_map = {cx.index: cx for cx in self.complexes}  # ADDED

        if laps:
            self.force_model.mode = "COMPARISON"
        else:
            self.force_model.mode = "DEVELOPMENT"

        self.sector_target = {}
        for sector in self.sectors:
            st = self._compute_sector_time(fastest.trace, sector)
            if st > 0:
                self.sector_target[sector.index] = st

        log.info(
            "Composite built: %d corners, %d sectors, %d ref laps, fastest=%.3fs",
            len(self.corners), len(self.sectors), len(laps), fastest.lap_time,
        )

    def _compute_sector_time(self, trace: 'LapTrace', sector: Sector) -> float:
        if not trace.points:
            return 0.0
        if sector.wraps:
            pts = [p for p in trace.points if p.dist_m >= sector.start_m]
            pts += [p for p in trace.points if p.dist_m <= sector.end_m]
        else:
            pts = [p for p in trace.points
                   if sector.start_m <= p.dist_m <= sector.end_m]
        if len(pts) < 2:
            return 0.0
        total_time = 0.0
        for i in range(1, len(pts)):
            d = abs(pts[i].dist_m - pts[i-1].dist_m)
            if d > 1000:
                continue
            avg_speed_mps = ((pts[i].speed_kph + pts[i-1].speed_kph) / 2) / 3.6
            if avg_speed_mps > 1:
                total_time += d / avg_speed_mps
        return total_time

    def start(self):
        if not self.corners:
            self.speaker.say("No corners detected. Check your reference laps.")
            return

        self.phase = self.PHASE_COACHING
        self._corner_ready.clear()
        self._corner_data.clear()
        self._approach_fired.clear()
        self._post_fired.clear()
        self._all_points.clear()
        self._inside_corner = None
        self._last_dist = 0.0
        self._lap_start_time = 0.0
        self.last_lap_time = 0.0
        self.best_lap_time = 0.0
        self.all_lap_times = []
        self.lap_count = 0
        self._current_sector_idx = -1
        self._sector_enter_time = 0.0
        self.sector_results = []
        self.sector_pb = {}
        self.last_sector_results = []

        self.speaker.say(
            f"{len(self.corners)} corners, {len(self.sectors)} sectors. "
            f"Drive when ready."
        )
        self._notify()

    def stop(self):
        self.phase = self.PHASE_WAITING
        self.speaker.say("Coach stopped.")
        self._notify()

    def feed(self, dist_m: float, speed_kph: float, speed_mps: float,
             throttle: float, brake: float, steer: float, gear: int,
             world_x: float = 0.0, world_y: float = 0.0, world_z: float = 0.0):

        if not hasattr(self, '_feed_call_count'):
            self._feed_call_count = 0
        self._feed_call_count += 1
        if self._feed_call_count <= 5 or self._feed_call_count % 200 == 0:
            log.info("🔧 feed() #%d: dist=%.0fm speed=%.1fkph(%.1fm/s) phase=%s corners=%d",
                     self._feed_call_count, dist_m, speed_kph, speed_mps,
                     self.phase, len(self.corners))

        if speed_mps < MIN_SPEED_MPS:
            return

        self.live_speed = speed_kph
        self.live_throttle = throttle * 100
        self.live_brake = brake * 100
        self.live_gear = gear
        self.live_dist = dist_m
        self.live_x = world_x
        self.live_z = world_z

        if self.phase != self.PHASE_COACHING or not self.corners:
            return

        point = TelPoint(
            dist_m=dist_m, speed_kph=speed_kph,
            throttle_pct=throttle * 100, brake_pct=brake * 100,
            steer_pct=steer * 100, gear=gear, timestamp=time.time(),
            world_x=world_x, world_y=world_y, world_z=world_z,
        )
        self._all_points.append(point)

        if len(self._all_points) % (POLL_HZ * 2) == 0:
            ready = len(self._corner_ready)
            total = len(self.corners)
            log.info("📊 dist=%.0fm speed=%.0fkph corners_ready=%d/%d lap=%d",
                     point.dist_m, point.speed_kph, ready, total, self.lap_count)

        max_points = int(POLL_HZ * 300)
        if len(self._all_points) > max_points:
            self._all_points = self._all_points[-max_points:]

        track_len = self.composite.track_length if self.composite else 0
        crossed_line = (
            self._last_dist > 0
            and dist_m < self._last_dist - 1000
            and (self._last_dist > track_len * 0.5 if track_len else False)
        )
        self._last_dist = dist_m

        if crossed_line:
            self.lap_count += 1
            self._approach_fired.clear()
            self._post_fired.clear()
            ready_count = len(self._corner_ready)
            total_count = len(self.corners)

            now = time.time()
            if self._lap_start_time > 0:
                self.last_lap_time = now - self._lap_start_time
                self.all_lap_times.append(self.last_lap_time)

                is_pb = (self.best_lap_time == 0
                         or self.last_lap_time < self.best_lap_time)
                if is_pb:
                    self.best_lap_time = self.last_lap_time

            self._lap_start_time = now

            if self.sector_results:
                self.last_sector_results = self.sector_results[:]
            self.sector_results = []
            self._current_sector_idx = -1
            self._sector_enter_time = 0.0

            lap_time_str = ""
            if self.last_lap_time > 0:
                lt_min = int(self.last_lap_time) // 60
                lt_sec = self.last_lap_time - lt_min * 60
                if lt_min > 0:
                    lap_time_str = f"{lt_min} {lt_sec:.1f}"
                else:
                    lap_time_str = f"{lt_sec:.1f} seconds"

            if ready_count < total_count:
                self.speaker.say(
                    f"Lap {self.lap_count}. "
                    f"Learning. {ready_count} of {total_count} corners ready."
                )
            elif self.last_lap_time > 0:
                if is_pb and self.lap_count > 2:
                    self.speaker.say(
                        f"Lap {self.lap_count}. {lap_time_str}. Personal best!"
                    )
                else:
                    delta = self.last_lap_time - self.best_lap_time
                    if delta > 0.5 and self.best_lap_time > 0:
                        self.speaker.say(
                            f"Lap {self.lap_count}. {lap_time_str}. "
                            f"Plus {delta:.1f} to your best."
                        )
                    else:
                        self.speaker.say(f"Lap {self.lap_count}. {lap_time_str}.")
                        else:
                self.speaker.say(f"Lap {self.lap_count}. All corners active.")
            self._notify()
            
            # Update focus turn tracking at end of lap
            self._update_focus_turn_tracking()

        self._record_corner_data(point)
        self._check_sector_crossing(point)

        for corner in self.corners:
            if corner.index in self._corner_ready:
                self._check_approach_cue(corner, point)
                self._check_post_cue(corner, point)
                # Also check for focus turn cues
                self._check_focus_turn_cue(corner, point)

    # ── Corner data recording ──

    def _record_corner_data(self, point: TelPoint):
        if not self.corners:
            return
        for corner in self.corners:
            zone_start = corner.brake_point_m - 100
            zone_end = corner.exit_m + 100
            in_zone = zone_start <= point.dist_m <= zone_end

            if in_zone:
                if corner.index not in self._corner_data:
                    self._corner_data[corner.index] = []
                    log.info("📍 Entering C%d zone (%.0fm, zone: %.0f-%.0fm)",
                             corner.index, point.dist_m, zone_start, zone_end)
                self._corner_data[corner.index].append(point)

            if (corner.index in self._corner_data
                    and corner.index not in self._corner_ready
                    and point.dist_m > zone_end):
                pts = len(self._corner_data[corner.index])
                if pts >= 5:
                    self._corner_ready.add(corner.index)
                    if self.composite:
                        data = self._corner_data[corner.index]
                        trace = LapTrace(points=data)
                        apex_pt = trace.get_at_dist(corner.apex_m, window=50)
                        if apex_pt:
                            self.composite.set_player_level(
                                corner.index, apex_pt.speed_kph
                            )
                    log.info("✅ C%d READY (%d pts)", corner.index, pts)

    def _get_driver_trace_for_corner(self, corner: Corner) -> Optional[LapTrace]:
        data = self._corner_data.get(corner.index)
        if not data or len(data) < 5:
            return None
        return LapTrace(points=data)

    # ── Sector timing ──

    def _check_sector_crossing(self, point: TelPoint):
        if not self.sectors:
            return

        now = time.time()
        dist = point.dist_m

        new_sector_idx = -1
        for s in self.sectors:
            if s.wraps:
                if dist >= s.start_m or dist < s.end_m:
                    new_sector_idx = s.index
                    break
            else:
                if s.start_m <= dist < s.end_m:
                    new_sector_idx = s.index
                    break

        if new_sector_idx == -1 or new_sector_idx == self._current_sector_idx:
            return

        old_idx = self._current_sector_idx

        if old_idx >= 0 and self._sector_enter_time > 0:
            sector_time = now - self._sector_enter_time

            if 2.0 < sector_time < 120.0:
                result = self._grade_sector(old_idx, sector_time)
                self.sector_results.append(result)

                if old_idx not in self.sector_pb or sector_time < self.sector_pb[old_idx]:
                    self.sector_pb[old_idx] = sector_time

                log.info("⏱️ S%d: %.3fs (PB: %.3fs, target: %.3fs) [%s]",
                         old_idx, sector_time,
                         self.sector_pb.get(old_idx, 0),
                         self.sector_target.get(old_idx, 0),
                         result.overall_grade())

        self._current_sector_idx = new_sector_idx
        self._sector_enter_time = now

    def _grade_sector(self, sector_idx: int, sector_time: float) -> SectorResult:
        result = SectorResult(sector_idx=sector_idx, time=sector_time)

        target = self.sector_target.get(sector_idx, 0)
        if target > 0:
            result.delta_to_target = sector_time - target

        pb = self.sector_pb.get(sector_idx, 0)
        if pb > 0:
            result.delta_to_pb = sector_time - pb

        corner = None
        for c in self.corners:
            if c.index == sector_idx:
                corner = c
                break
        if not corner:
            return result

        driver_trace = self._get_driver_trace_for_corner(corner)
        if not driver_trace:
            return result

        ct = self.composite.targets.get(sector_idx) if self.composite else None
        ref_trace = ct.target_trace if ct else None

        if ct:
            driver_brake = driver_trace.find_brake_point(corner, search_range=200)
            if driver_brake is not None:
                delta = abs(driver_brake - ct.target_brake_m)
                if delta < 10:
                    result.brake_grade = "good"
                elif delta < 30:
                    result.brake_grade = "ok"
                else:
                    result.brake_grade = "poor"

        drv_brake_pt = driver_trace.get_at_dist(corner.brake_point_m + 20, window=20)
        ref_brake_pt = ref_trace.get_at_dist(corner.brake_point_m + 20, window=20) if ref_trace else None
        if drv_brake_pt and ref_brake_pt:
            p_diff = abs(drv_brake_pt.brake_pct - ref_brake_pt.brake_pct)
            if p_diff < 10:
                result.pressure_grade = "good"
            elif p_diff < 25:
                result.pressure_grade = "ok"
            else:
                result.pressure_grade = "poor"

        drv_turnin = None
        ref_turnin = None
        for p in driver_trace.points:
            if p.dist_m > corner.brake_point_m and abs(p.steer_pct) > 5:
                drv_turnin = p.dist_m
                break
        if ref_trace:
            for p in ref_trace.points:
                if p.dist_m > corner.brake_point_m and p.dist_m < corner.exit_m:
                    if abs(p.steer_pct) > 5:
                        ref_turnin = p.dist_m
                        break
        if drv_turnin and ref_turnin:
            delta = abs(drv_turnin - ref_turnin)
            if delta < 10:
                result.turn_in_grade = "good"
            elif delta < 25:
                result.turn_in_grade = "ok"
            else:
                result.turn_in_grade = "poor"

        drv_apex = driver_trace.get_at_dist(corner.apex_m, window=30)
        if drv_apex and ct:
            speed_diff = ct.target_apex_speed - drv_apex.speed_kph
            if speed_diff < 5:
                result.apex_grade = "good"
            elif speed_diff < 15:
                result.apex_grade = "ok"
            else:
                result.apex_grade = "poor"

        drv_exit = driver_trace.get_at_dist(corner.exit_m, window=30)
        if drv_exit and ct:
            exit_diff = ct.target_exit_speed - drv_exit.speed_kph
            if exit_diff < 5:
                result.exit_grade = "good"
            elif exit_diff < 15:
                result.exit_grade = "ok"
            else:
                result.exit_grade = "poor"

        if ref_trace and ref_trace._spline_dists:
            deviations = []
            for zone_dist in [corner.apex_m,
                              corner.brake_point_m + (corner.apex_m - corner.brake_point_m) * 0.3,
                              corner.apex_m + (corner.exit_m - corner.apex_m) * 0.7]:
                drv_pt = driver_trace.get_at_dist(zone_dist, window=30)
                if drv_pt and (abs(drv_pt.world_x) > 0.1 or abs(drv_pt.world_z) > 0.1):
                    dev = ref_trace.get_lateral_deviation(zone_dist, drv_pt.world_x, drv_pt.world_z)
                    if dev is not None:
                        deviations.append(abs(dev))
            if deviations:
                avg_dev = sum(deviations) / len(deviations)
                if avg_dev < 1.5:
                    result.line_grade = "good"
                elif avg_dev < 3.0:
                    result.line_grade = "ok"
                else:
                    result.line_grade = "poor"

        return result

    # ── Approach cue ──

    def _get_complex_for_corner(self, corner_index: int) -> Optional[Complex]:
        for cx in self.complexes:
            if corner_index in cx.corner_indices:
                return cx
        return None

    def _get_complex_role(self, corner_index: int, cx: Complex) -> str:
        if corner_index == cx.corner_indices[0]:
            return "entry"
        elif corner_index == cx.corner_indices[-1]:
            return "exit"
        return "mid"

    def _check_approach_cue(self, corner: Corner, point: TelPoint):
        if corner.index in self._approach_fired:
            return
        if abs(point.dist_m - corner.approach_m) > APPROACH_WINDOW_M:
            return
        if point.dist_m > corner.brake_point_m:
            return

        self._approach_fired.add(corner.index)

        ct = self.composite.targets.get(corner.index) if self.composite else None
        instruction = self._generate_instruction(corner, ct)

        cx = self._get_complex_for_corner(corner.index)
        if cx and instruction:
            role = self._get_complex_role(corner.index, cx)
            if role == "entry":
                instruction = self._add_complex_approach_context(instruction, corner, cx)

        if instruction:
            self.current_corner_label = f"C{corner.index}: {instruction}"
            self.speaker.say_priority(instruction)
        self._notify()

    def _add_complex_approach_context(self, instruction: str, corner: Corner,
                                      cx: Complex) -> str:
        n_corners = len(cx.corner_indices)
        ctype = cx.complex_type

        if ctype == "esses":
            n = cx.n_direction_changes or n_corners
            return (f"{instruction} Esses ahead, {n} direction changes. "
                    f"Stay committed through the whole complex.")
        elif ctype == "flow_zone":
            n = cx.n_direction_changes
            return (f"{instruction} Flow zone ahead, {n} direction changes. "
                    f"One brake, then carry speed through. Focus on the exit.")
        elif ctype == "chicane":
            return f"{instruction} Chicane ahead. Sacrifice entry for the exit."
        elif ctype == "double_apex":
            return f"{instruction} Double apex. Patience on the first, drive the second."
        else:
            return f"{instruction} Linked corners ahead. Think about the whole sequence."

    # ── Post-corner feedback ──

    def _check_post_cue(self, corner: Corner, point: TelPoint):
        if corner.index in self._post_fired:
            return
        post_dist = corner.exit_m + POST_CORNER_M
        if abs(point.dist_m - post_dist) > APPROACH_WINDOW_M:
            return

        self._post_fired.add(corner.index)
        self.current_corner_label = ""
        self._notify()

        driver_trace = self._get_driver_trace_for_corner(corner)
        ct = self.composite.targets.get(corner.index) if self.composite else None

        if driver_trace and self.composite:
            apex_pt = driver_trace.get_at_dist(corner.apex_m, window=30)
            if apex_pt:
                promoted = self.composite.check_promotion(
                    corner.index, apex_pt.speed_kph
                )
                if promoted:
                    ct = self.composite.targets[corner.index]
                    self.speaker.say_priority(
                        f"Corner {corner.index} promoted to tier {ct.tier + 1}. "
                        f"New target. Faster."
                    )
                else:
                    # Try complex feedback first
                    complex_feedback = None
                    for cx in self.complexes:
                        if corner.index == cx.corner_indices[-1]:  # Last corner of complex
                            complex_feedback = self._generate_complex_feedback(cx, driver_trace)
                            break
                    
                    if complex_feedback:
                        self.speaker.say_priority(complex_feedback)
                                        else:
                        feedback = self._generate_post_feedback(corner, ct, driver_trace)
                        if feedback:
                            self.speaker.say_priority(feedback)
                        # Also give focus turn feedback if this is a focus turn
                        if corner.index in self.focus_turns:
                            self._give_focus_turn_feedback(corner.index)

        zone_start = corner.brake_point_m - 50
        fresh_points = [p for p in self._all_points
                        if zone_start <= p.dist_m <= corner.exit_m + 50
                        and p.timestamp > time.time() - 30]
        if len(fresh_points) > 5:
            self._corner_data[corner.index] = fresh_points
            if self.composite:
                trace = LapTrace(points=fresh_points)
                apex_pt = trace.get_at_dist(corner.apex_m, window=50)
                if apex_pt:
                    self.composite.set_player_level(corner.index, apex_pt.speed_kph)

    # ── REPLACED: Enhanced instruction generation ──
    def _generate_instruction(self, corner: Corner,
                              ct: Optional[CornerTarget]) -> str:
        """Generate pre-corner instruction using enhanced phrases."""
        driver_trace = self._get_driver_trace_for_corner(corner)
        if not driver_trace:
            return ""

        if ct and ct.target_trace:
            ref_trace = ct.target_trace
            ref_brake_m = ct.target_brake_m
            ref_apex_speed = ct.target_apex_speed
            ref_exit_speed = ct.target_exit_speed
        else:
            ref_trace = None
            ref_brake_m = corner.brake_point_m
            ref_apex_speed = corner.apex_speed_kph
            ref_exit_speed = corner.exit_speed_kph

        driver_brake_m = driver_trace.find_brake_point(corner, search_range=250)
        driver_apex = driver_trace.get_at_dist(corner.apex_m, window=30)
        driver_exit = driver_trace.get_at_dist(corner.exit_m, window=30)

        complex_name = ""
        complex_corners = ""
        for cx in self.complexes:
            if corner.index in cx.corner_indices:
                if len(cx.corner_indices) > 1:
                    complex_name = cx.complex_type
                    complex_corners = ','.join(str(i) for i in cx.corner_indices)
                break

        if driver_brake_m is not None and ct:
            delta = driver_brake_m - ref_brake_m
            if delta < -8:
                msg = self.enhanced_coach.generate_pre(
                    corner.index, 'brake_early', delta=abs(delta),
                    complex_name=complex_name, corners=complex_corners
                )
                if msg:
                    return msg

        if driver_apex and ct:
            delta = ref_apex_speed - driver_apex.speed_kph
            if delta > 8:
                msg = self.enhanced_coach.generate_pre(
                    corner.index, 'apex_slow', delta=delta,
                    complex_name=complex_name, corners=complex_corners
                )
                if msg:
                    return msg

        if driver_exit and ct:
            delta = ref_exit_speed - driver_exit.speed_kph
            if delta > 10:
                msg = self.enhanced_coach.generate_pre(
                    corner.index, 'exit_slow', delta=delta,
                    complex_name=complex_name, corners=complex_corners
                )
                if msg:
                    return msg

        if driver_apex and driver_brake_m:
            apex_brake_pt = driver_trace.get_at_dist(corner.apex_m, window=20)
            if apex_brake_pt and apex_brake_pt.brake_pct < 5:
                brake_pts = [p for p in driver_trace.points 
                           if corner.brake_point_m - 20 <= p.dist_m <= corner.brake_point_m + 50]
                if brake_pts and max(p.brake_pct for p in brake_pts) > 60:
                    msg = self.enhanced_coach.generate_pre(
                        corner.index, 'no_trail_brake',
                        complex_name=complex_name, corners=complex_corners
                    )
                    if msg:
                        return msg

        return ""

    # ── REPLACED: Enhanced post feedback ──
    def _generate_post_feedback(self, corner: Corner,
                                 ct: Optional[CornerTarget],
                                 driver_trace: LapTrace) -> str:
        """Generate post-corner feedback using enhanced phrases."""
        if not ct or not ct.target_trace:
            return ""

        driver_brake_m = driver_trace.find_brake_point(corner, search_range=250)
        driver_apex = driver_trace.get_at_dist(corner.apex_m, window=30)
        driver_exit = driver_trace.get_at_dist(corner.exit_m, window=30)

        complex_name = ""
        complex_corners = ""
        for cx in self.complexes:
            if corner.index in cx.corner_indices:
                if len(cx.corner_indices) > 1:
                    complex_name = cx.complex_type
                    complex_corners = ','.join(str(i) for i in cx.corner_indices)
                break

        if driver_brake_m:
            delta = driver_brake_m - ct.target_brake_m
            if delta < -8:
                msg = self.enhanced_coach.generate_post(
                    corner.index, 'brake_early', delta=abs(delta),
                    complex_name=complex_name, corners=complex_corners
                )
                if msg:
                    return msg

        if driver_apex:
            delta = ct.target_apex_speed - driver_apex.speed_kph
            if delta > 8:
                msg = self.enhanced_coach.generate_post(
                    corner.index, 'apex_slow', delta=delta,
                    complex_name=complex_name, corners=complex_corners
                )
                if msg:
                    return msg

        if driver_exit:
            delta = ct.target_exit_speed - driver_exit.speed_kph
            if delta > 10:
                msg = self.enhanced_coach.generate_post(
                    corner.index, 'exit_slow', delta=delta,
                    complex_name=complex_name, corners=complex_corners
                )
                if msg:
                    return msg

        if driver_apex and driver_brake_m:
            apex_brake_pt = driver_trace.get_at_dist(corner.apex_m, window=20)
            if apex_brake_pt and apex_brake_pt.brake_pct < 5:
                brake_pts = [p for p in driver_trace.points 
                           if corner.brake_point_m - 20 <= p.dist_m <= corner.brake_point_m + 50]
                if brake_pts and max(p.brake_pct for p in brake_pts) > 60:
                    msg = self.enhanced_coach.generate_post(
                        corner.index, 'no_trail_brake',
                        complex_name=complex_name, corners=complex_corners
                    )
                    if msg:
                        return msg

        return ""

    # ── ADDED: Complex feedback generation ──
    def _generate_complex_feedback(self, cx: Complex,
                                    driver_trace: LapTrace) -> str:
        """Generate sequence-level feedback for a corner complex."""
        if not hasattr(self, 'composite') or not self.composite:
            return ""

        first_corner = cx.corners[0]
        ct = self.composite.targets.get(first_corner.index)
        if not ct or not ct.target_trace:
            return ""

        zone_points = [p for p in driver_trace.points 
                       if cx.start_m <= p.dist_m <= cx.end_m]
        ref_points = [p for p in ct.target_trace.points 
                     if cx.start_m <= p.dist_m <= cx.end_m]

        if len(zone_points) < 10 or len(ref_points) < 10:
            return ""

        min_speed = min(p.speed_kph for p in zone_points)
        exit_speed = zone_points[-1].speed_kph
        ref_min = min(p.speed_kph for p in ref_points)
        ref_exit = ref_points[-1].speed_kph

        min_diff = ref_min - min_speed
        exit_diff = ref_exit - exit_speed

        corners = ','.join(str(i) for i in cx.corner_indices)

        if min_diff > 15:
            return self.enhanced_coach.generate_pre(
                cx.index, 'complex_min_speed', value=min_diff,
                complex_name=cx.complex_type, corners=corners
            )
        elif exit_diff > 15:
            return self.enhanced_coach.generate_pre(
                cx.index, 'complex_exit_speed', value=exit_diff,
                complex_name=cx.complex_type, corners=corners
            )

        return ""

    def _generate_complex_feedback(self, cx: Complex,
                                    driver_trace: LapTrace) -> str:
        # ... [keep your existing complex feedback code] ...
        pass

    # ── Keep all your existing methods below this line ──
    # (escalate_feedback, _notify, etc.)

    def _escalate_feedback(self, prefix: str, tag: str, base_msg: str,
                            count: int, corner: Corner) -> str:
        # ... [keep your existing code] ...
        pass

    def _notify(self):
        if self.on_state_change:
            self.on_state_change()

# ═══════════════════════════════════════════════════════════════════════════
# ENHANCED COACHING GENERATOR - NEW
# ═══════════════════════════════════════════════════════════════════════════
class EnhancedCoachingGenerator:
    """
    Provides varied phrases, complex awareness, and How-To formula.
    """
    
    def __init__(self):
        self.coaching_history = {}  # Track what we've said
        self._init_phrases()
    
    def _init_phrases(self):
        """5 variations for each message type."""
        self.phrases = {
            'brake_early_pre': [
                "Corner {idx}: brake {delta:.0f}m later. Look further ahead, squeeze don't stamp.",
                "C{idx}: you're braking early. Move your marker {delta:.0f}m later.",
                "Into {idx}, brake {delta:.0f}m later than you think. Trust the car.",
                "Corner {idx} approaching: brake point {delta:.0f}m too early. Later marker, commit.",
                "C{idx}: early brakes. Pick a later board, squeeze progressively."
            ],
            'brake_early_post': [
                "C{idx}: braked {delta:.0f}m early. Next lap, later marker, commit.",
                "Early at {idx}. Move it back {delta:.0f}m next time.",
                "{idx}: {delta:.0f}m early on brakes. Later point, smoother squeeze.",
                "Lost time at {idx} entry. Brake {delta:.0f}m later next lap.",
                "C{idx} early. Trust the brakes more next time."
            ],
            'apex_slow_pre': [
                "C{idx}: losing {delta:.0f}kph at apex. Turn in 5m later, clip the inside.",
                "Corner {idx}: slow through apex. Later entry, carry more speed.",
                "Through {idx}, you're {delta:.0f}kph slow. Late apex = fast exit.",
                "C{idx} apex: {delta:.0f}kph down. Delay turn-in, trust the grip.",
                "Into {idx}: late apex needed. Sacrifice entry for exit speed."
            ],
            'apex_slow_post': [
                "C{idx}: {delta:.0f}kph slow apex. Later turn-in next lap.",
                "Slow at {idx} apex. Turn in later, carry more.",
                "{idx} apex: {delta:.0f}kph down. Delay entry next time.",
                "Lost apex speed at {idx}. Later turn-in = more exit speed.",
                "C{idx} apex slow. Trust the lateral grip more."
            ],
            'exit_slow_pre': [
                "C{idx}: losing {delta:.0f}kph on exit. Apex first, then power.",
                "Corner {idx} exit: {delta:.0f}kph down. Get straight earlier.",
                "Through {idx}, you're slow on exit. Nail the apex, power follows.",
                "C{idx}: exit loss. Focus on apex, then squeeze throttle.",
                "Into {idx}: exit speed critical. Perfect apex = early power."
            ],
            'exit_slow_post': [
                "C{idx} exit: lost {delta:.0f}kph. Fix the apex next lap.",
                "Slow exit at {idx}. Apex was the problem.",
                "{idx}: {delta:.0f}kph lost on exit. Earlier apex next time.",
                "Exit loss at {idx}. Apex first, then power.",
                "C{idx} exit slow. Hit the apex perfectly next lap."
            ],
            'no_trail_brake_pre': [
                "C{idx}: need trail brake. Keep 20% brake into the turn.",
                "Corner {idx}: don't dump the brake. Trail it through entry.",
                "Into {idx}: brake while turning. 20% at turn-in.",
                "C{idx}: cliff release. Trail brake into the corner.",
                "Corner {idx}: smooth brake release. Keep pressure past turn-in."
            ],
            'no_trail_brake_post': [
                "C{idx}: no trail brake. Next lap, keep foot on pedal while turning.",
                "Dumped brake at {idx}. Trail next time.",
                "{idx}: cliff release. Brake into the corner next lap.",
                "Lost rotation at {idx}. Trail brake will fix it.",
                "C{idx}: brake release too fast. Trail it next time."
            ],
            'brake_stab_pre': [
                "C{idx}: stabbing brakes. One smooth squeeze, hold, release.",
                "Corner {idx}: pumping the brakes. Squeeze once, hold it.",
                "Into {idx}: too much modulation. One firm squeeze.",
                "C{idx}: brake stabbing. Smooth is fast.",
                "Corner {idx}: brake once, not multiple times."
            ],
            'brake_stab_post': [
                "C{idx}: brake stabbing. One squeeze next time.",
                "Too much modulation at {idx}. Smooth application.",
                "{idx}: pumped the brakes. One firm squeeze next lap.",
                "Brake stabbing at {idx}. Trust one application.",
                "C{idx}: smooth it out next time."
            ],
            'complex_min_speed_pre': [
                "Through {name} (C{corners}): losing {value:.0f}kph. Brake ONCE, then flow.",
                "{name} ahead: one brake zone only. Carry momentum.",
                "In the {name}: brake early ONCE, then steer. Don't touch brakes again.",
                "{name}: {value:.0f}kph slow. One brake, trust the flow.",
                "Through {name}: momentum is key. Brake once, steer twice."
            ],
            'complex_min_speed_post': [
                "{name}: {value:.0f}kph slow. Braked twice—they braked once.",
                "Lost {value:.0f}kph in {name}. One brake next time.",
                "{name}: too many brakes. One zone only.",
                "Through {name}: you braked twice. They braked once.",
                "{name} speed loss: one brake zone next lap."
            ],
            'complex_exit_speed_pre': [
                "{name} exit: losing {value:.0f}kph. Focus on last corner apex.",
                "Through {name}: exit speed critical. Nail the final corner.",
                "{name}: sacrifice entry, nail the exit.",
                "Exit speed low in {name}. Last corner apex is everything.",
                "{name}: {value:.0f}kph lost. Perfect the final apex."
            ],
            'complex_exit_speed_post': [
                "{name} exit: {value:.0f}kph down. Last corner apex next time.",
                "Lost exit speed in {name}. Focus on final corner.",
                "{name}: {value:.0f}kph lost. Nail the last apex.",
                "Exit loss in {name}. Last corner was the problem.",
                "{name} exit slow. Perfect that final corner."
            ]
        }
    
    def _get_key(self, corner_idx, issue_type, pre=True):
        """Get unique key for history tracking."""
        return f"{corner_idx}_{issue_type}_{'pre' if pre else 'post'}"
    
    def generate_pre(self, corner_idx, issue_type, delta=0, value=0, 
                     complex_name="", corners=""):
        """Generate pre-corner advice with 5 variations."""
        key = f"{issue_type}_pre"
        if key not in self.phrases:
            return None
            
        history_key = self._get_key(corner_idx, issue_type, pre=True)
        used_idx = self.coaching_history.get(history_key, -1)
        next_idx = (used_idx + 1) % len(self.phrases[key])
        self.coaching_history[history_key] = next_idx
        
        phrase = self.phrases[key][next_idx]
        
        if complex_name:
            return phrase.format(idx=corner_idx, delta=abs(delta), 
                               value=abs(value), name=complex_name, corners=corners)
        else:
            return phrase.format(idx=corner_idx, delta=abs(delta))
    
    def generate_post(self, corner_idx, issue_type, delta=0, value=0,
                      complex_name="", corners=""):
        """Generate post-corner advice with 5 variations."""
        key = f"{issue_type}_post"
        if key not in self.phrases:
            return None
            
        history_key = self._get_key(corner_idx, issue_type, pre=False)
        used_idx = self.coaching_history.get(history_key, -1)
        next_idx = (used_idx + 1) % len(self.phrases[key])
        self.coaching_history[history_key] = next_idx
        
        phrase = self.phrases[key][next_idx]
        
        if complex_name:
            return phrase.format(idx=corner_idx, delta=abs(delta), 
                               value=abs(value), name=complex_name, corners=corners)
        else:
            return phrase.format(idx=corner_idx, delta=abs(delta))



