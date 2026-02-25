# -*- coding: utf-8 -*-
from __future__ import annotations
import time
import math
from collections import deque
from typing import List, Optional, Dict, Set, Tuple
import logging

from senna_ai.track.corner_detection import Corner, Sector, SectorResult, CornerTarget, build_sectors
from senna_ai.track.composite_builder import CompositeLap
from senna_ai.track.complex_detection import Complex, detect_complexes  
from senna_ai.track.force_stage_model import ForceStageModel
from senna_ai.track.track_model import TrackModel

from senna_ai.telemetry.models import TelPoint, LapTrace, RefLapFile
from senna_ai.coaching.coaching_constants import *
from senna_ai.coaching.coaching_constants import MIN_SPEED_MPS
from senna_ai.coaching.coaching_constants import BRAKE_THRESHOLD
from senna_ai.coaching.coaching_constants import TIER_PROMOTION_LAPS
from senna_ai.infra.tts_engine import Speaker
from senna_ai.coaching.race_engineer import RaceEngineerCoach

log = logging.getLogger(__name__)

# Temporary imports from monolith (until fully extracted)


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
        self.reference_line = None  # placeholder for future geometry coaching


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
        
        # Speech generation: minimal race-engineer style
        self.enhanced_coach = RaceEngineerCoach()
        
        # Strategic Lap Focus Model
        self.lap_focus_entities: Set[int] = set()  # Set of entity indices (corner or complex)
        self.last_focus_entities: Set[int] = set()  # Focus entities from previous lap
        self.entity_time_loss: Dict[int, float] = {}  # Time loss per entity (corner/complex)
        self.entity_improvement_history: Dict[int, List[float]] = {}  # Track improvement per entity
        
        # Speech budget tracking
        self.speech_budget_max = MAX_FOCUS_ENTITIES * 2  # 6: approach + post per entity
        self.corner_events_this_lap: List[dict] = []  # list of dicts: corner_idx, delta, dist, issue_type, timestamp
        self.speeches_this_lap: List[dict] = []  # list of dicts: dist, source, corner_idx, timestamp
        self.min_speech_spacing_m = MIN_SPACING_M
        self.entities_spoken_this_lap: Set[int] = set()  # entities coached this lap (diagnostic)

        # Per-lap comparison tracking
        self._prev_corner_data: dict[int, list[TelPoint]] = {}  # corner data from previous lap
        self._corner_advice_type: dict[int, str] = {}  # issue type from approach cue given this lap

        # ── Section engine state ──────────────────────────────────────────────
        # Reset each lap (which sections have fired)
        self._section_approach_fired: set[int] = set()    # cx.index values with approach cue fired
        self._section_post_fired:     set[int] = set()    # cx.index values with post cue fired
        # Timing within current lap (reset each lap)
        self._section_enter_time:     dict[int, float] = {}   # cx.index → timestamp at cx.start_m
        self._section_exit_time:      dict[int, float] = {}   # cx.index → timestamp at cx.end_m
        # Cross-lap history (NOT reset each lap)
        self._section_lap_times:      dict[int, deque]  = {}  # cx.index → deque(maxlen=5) of times
        self._section_best_time:      dict[int, float]  = {}  # cx.index → fastest time seen

    def set_reference_laps(self, laps: list[RefLapFile]):
        """Set ALL reference laps for the current track. Builds composite."""
        self.ref_laps = laps

        from senna_ai.track.corner_detection import detect_corners

        # Ensure corners exist on reference laps    
        for lap in laps:
            if getattr(lap, "trace", None) and getattr(lap.trace, "points", None):
                if not getattr(lap, "corners", None):
                    lap.corners = detect_corners(lap.trace.points)






        if not laps:
            return

        viable = [l for l in laps if l.corners and len(l.corners) >= 3
                  and l.lap_time > 0 and len(l.trace.points) >= 100]
        if not viable:
            viable = [l for l in laps if l.corners and l.lap_time > 0]
        if not viable:
            log.warning("No reference laps have detected corners — cannot build composite.")
            return

        # Remove isolated fast-cluster outliers (cheat laps, flying laps, in-laps)
        from senna_ai.data.lap_scanner import filter_laps_by_cluster
        filtered = filter_laps_by_cluster(viable, gap_threshold=5.0)
        if filtered:
            viable = filtered
        else:
            log.warning("Cluster filter removed all laps — falling back to unfiltered set.")

        from collections import Counter
        corner_counts = Counter(len(l.corners) for l in viable)
        modal_count = corner_counts.most_common(1)[0][0]
        log.info(   
            "Modal corner count selected: %d (distribution=%s)",
            modal_count,
            dict(corner_counts),
        )
        

        geometry_candidates = [
            l for l in viable if len(l.corners) == modal_count
        ]
        fastest = min(geometry_candidates, key=lambda l: l.lap_time)
        
        
        

        log.info(
            "Geometry ref: %s (%.3fs, %d corners) — modal_count=%d across %d viable laps",
            fastest.car_name[:30],
            fastest.lap_time,
            len(fastest.corners),
            modal_count,
            len(viable),
)
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
            self._speak("No corners detected. Check your reference laps.", source="start_no_corners")
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

        self._speak(
            f"{len(self.corners)} corners, {len(self.sectors)} sectors. Drive when ready.",
            source="start_coaching"
        )
        self._notify()

    def stop(self):
        self.phase = self.PHASE_WAITING
        self._speak("Coach stopped.", source="stop")
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

        # 1️⃣ Add log before coaching evaluation begins
        log.info("🟡 Coaching check: dist=%.0fm phase=%s", dist_m, self.phase)

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
            # Save corner data snapshot for post-feedback comparison next lap
            self._prev_corner_data = {k: list(v) for k, v in self._corner_data.items()}
            self._corner_advice_type.clear()
            # Reset section engine for new lap (history deques persist across laps)
            self._section_approach_fired.clear()
            self._section_post_fired.clear()
            self._section_enter_time.clear()
            self._section_exit_time.clear()
            # Reset speech tracking for new lap
            self.corner_events_this_lap.clear()
            self.speeches_this_lap.clear()
            self.entities_spoken_this_lap.clear()
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
                self._speak(
                    f"Lap {self.lap_count}. Learning. {ready_count} of {total_count} corners ready.",
                    source="lap_completion_learning"
                )
            elif self.last_lap_time > 0:
                if is_pb and self.lap_count > 2:
                    self._speak(
                        f"Lap {self.lap_count}. {lap_time_str}. Personal best!",
                        source="lap_completion_pb"
                    )
                else:
                    delta = self.last_lap_time - self.best_lap_time
                    if delta > 0.5 and self.best_lap_time > 0:
                        self._speak(
                            f"Lap {self.lap_count}. {lap_time_str}. Plus {delta:.1f} to your best.",
                            source="lap_completion_delta"
                        )
            else:
                self._speak(f"Lap {self.lap_count}. All corners active.", source="lap_completion_all_active")
            
            # Compute strategic focus for next lap
            if self.lap_count > 1 and len(self._corner_ready) == len(self.corners):
                self.compute_lap_focus()
            
            self._notify()

        self._record_corner_data(point)
        self._check_sector_crossing(point)

        # Section engine — runs before corner loop so briefings fire first
        for cx in self.complexes:
            self._update_section_timing(cx, point)
            self._check_section_approach_cue(cx, point)
            self._check_section_post_cue(cx, point)

        for corner in self.corners:
            if corner.index in self._corner_ready:
                self._check_approach_cue(corner, point)
                self._check_post_cue(corner, point)

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

    def _find_apex_dist(self, trace: LapTrace, corner: Corner) -> Optional[float]:
        """Return dist_m where minimum speed occurs within the corner zone."""
        pts = [p for p in trace.points
               if corner.brake_point_m <= p.dist_m <= corner.exit_m and p.speed_kph > 0]
        if not pts:
            return None
        return min(pts, key=lambda p: p.speed_kph).dist_m

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

    def _get_entity_id(self, corner_idx: int, is_complex: bool = False) -> int:
        """Map a corner (or complex) index to its coaching entity ID.
        Complexes use negative IDs to match lap_focus_entities convention.
        If a corner belongs to a complex, return that complex's entity ID."""
        if is_complex:
            return -corner_idx
        for cx in self.complexes:
            if corner_idx in cx.corner_indices:
                return -cx.index
        return corner_idx

    def _get_complex_role(self, corner_index: int, cx: Complex) -> str:
        if corner_index == cx.corner_indices[0]:
            return "entry"
        elif corner_index == cx.corner_indices[-1]:
            return "exit"
        return "mid"

    def _check_approach_cue(self, corner: Corner, point: TelPoint):
        # Section engine gate: suppress individual cue if section briefing already fired
        cx = self._get_complex_for_corner(corner.index)
        if cx is not None and cx.index in self._section_approach_fired:
            return

        if corner.index in self._approach_fired:
            return
        if abs(point.dist_m - corner.approach_m) > APPROACH_WINDOW_M:
            return
        if point.dist_m > corner.brake_point_m:
            return

        self._approach_fired.add(corner.index)

        ct = self.composite.targets.get(corner.index) if self.composite else None
        instruction = self._generate_instruction(corner, ct)

        # 2️⃣ When a coaching condition is met (just before generating a message)
        if instruction:
            log.info("🟢 Coaching condition met for corner %d", corner.index)

        cx = self._get_complex_for_corner(corner.index)
        if cx and instruction:
            role = self._get_complex_role(corner.index, cx)
            if role == "entry":
                instruction = self._add_complex_approach_context(instruction, corner, cx)

        # 3️⃣ Immediately after generating the coaching message string
        if instruction:
            log.info("🗣 Generated coaching: %s", instruction)
            self.current_corner_label = f"C{corner.index}: {instruction}"
            self._speak(instruction, source=f"approach_cue_C{corner.index}", priority=True)
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

        # Section engine gate: suppress all individual corner feedback if section owns this complex
        cx = self._get_complex_for_corner(corner.index)
        if cx is not None and cx.index in self._section_approach_fired:
            return

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
                    promotion_message = f"Corner {corner.index} promoted to tier {ct.tier + 1}. New target. Faster."
                    # 2️⃣ When a coaching condition is met (just before generating a message)
                    log.info("🟢 Coaching condition met for corner %d (promotion)", corner.index)
                    # 3️⃣ Immediately after generating the coaching message string
                    log.info("🗣 Generated coaching: %s", promotion_message)
                    self._speak(promotion_message, source=f"corner_promotion_C{corner.index}", priority=True)
                else:
                    # Try complex feedback first
                    complex_feedback = None
                    for cx in self.complexes:
                        if corner.index == cx.corner_indices[-1]:  # Last corner of complex
                            complex_feedback = self._generate_complex_feedback(cx, driver_trace)
                            break
                    
                    if complex_feedback:
                        # 2️⃣ When a coaching condition is met (just before generating a message)
                        log.info("🟢 Coaching condition met for corner %d (complex feedback)", corner.index)
                        # 3️⃣ Immediately after generating the coaching message string
                        log.info("🗣 Generated coaching: %s", complex_feedback)
                        self._speak(complex_feedback, source=f"complex_feedback_C{cx.index}", priority=True)
                    else:
                        feedback = self._generate_post_feedback(corner, ct, driver_trace)
                        if feedback:
                            # 2️⃣ When a coaching condition is met (just before generating a message)
                            log.info("🟢 Coaching condition met for corner %d (post feedback)", corner.index)
                            # 3️⃣ Immediately after generating the coaching message string
                            log.info("🗣 Generated coaching: %s", feedback)
                            self._speak(feedback, source=f"post_feedback_C{corner.index}", priority=True)

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
        # ── Focus Model Gate ──
        if self.lap_focus_entities:
            # Direct corner focus
            if corner.index in self.lap_focus_entities:
                pass
            else:
                # Check if part of a focused complex
                in_focused_complex = any(
                    -cx.index in self.lap_focus_entities
                    and corner.index in cx.corner_indices
                    for cx in self.complexes
                )
                
                if not in_focused_complex:
                    return ""
        
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
                self._record_corner_event(corner.index, delta, self.live_dist, 'brake_early')
                msg = self.enhanced_coach.generate_instruction(
                    corner.index, 'brake_early', complex_name=complex_name
                )
                if msg:
                    self._corner_advice_type[corner.index] = 'brake_early'
                    return msg

        # ── Apex timing: driver's min-speed point is before the reference apex ──
        apex_dist = self._find_apex_dist(driver_trace, corner)
        if apex_dist is not None and apex_dist < corner.apex_m - 25:
            delta = corner.apex_m - apex_dist  # metres too early
            self._record_corner_event(corner.index, delta, self.live_dist, 'apex_early')
            msg = self.enhanced_coach.generate_instruction(
                corner.index, 'apex_early', complex_name=complex_name
            )
            if msg:
                self._corner_advice_type[corner.index] = 'apex_early'
                return msg

        # ── Line: lateral deviation from reference at apex (needs position data) ──
        if ref_trace and ref_trace._spline_dists and driver_trace.has_position_data():
            drv_apex_pt = driver_trace.get_at_dist(corner.apex_m, window=30)
            if drv_apex_pt and (abs(drv_apex_pt.world_x) > 0.1 or abs(drv_apex_pt.world_z) > 0.1):
                dev = ref_trace.get_lateral_deviation(
                    corner.apex_m, drv_apex_pt.world_x, drv_apex_pt.world_z
                )
                if dev is not None and abs(dev) > 1.5:
                    self._record_corner_event(corner.index, abs(dev), self.live_dist, 'line_wide')
                    msg = self.enhanced_coach.generate_instruction(
                        corner.index, 'line_wide', complex_name=complex_name
                    )
                    if msg:
                        self._corner_advice_type[corner.index] = 'line_wide'
                        return msg

        if driver_apex and ct:
            delta = ref_apex_speed - driver_apex.speed_kph
            if delta > 8:
                self._record_corner_event(corner.index, delta, self.live_dist, 'apex_slow')
                msg = self.enhanced_coach.generate_instruction(
                    corner.index, 'apex_slow', complex_name=complex_name
                )
                if msg:
                    self._corner_advice_type[corner.index] = 'apex_slow'
                    return msg

        if driver_exit and ct:
            delta = ref_exit_speed - driver_exit.speed_kph
            if delta > 10:
                self._record_corner_event(corner.index, delta, self.live_dist, 'exit_slow')
                msg = self.enhanced_coach.generate_instruction(
                    corner.index, 'exit_slow', complex_name=complex_name
                )
                if msg:
                    self._corner_advice_type[corner.index] = 'exit_slow'
                    return msg

        if driver_apex and driver_brake_m:
            apex_brake_pt = driver_trace.get_at_dist(corner.apex_m, window=20)
            if apex_brake_pt and apex_brake_pt.brake_pct < 5:
                brake_pts = [p for p in driver_trace.points
                           if corner.brake_point_m - 20 <= p.dist_m <= corner.brake_point_m + 50]
                if brake_pts and max(p.brake_pct for p in brake_pts) > 60:
                    self._record_corner_event(corner.index, 100, self.live_dist, 'no_trail_brake')
                    msg = self.enhanced_coach.generate_instruction(
                        corner.index, 'no_trail_brake', complex_name=complex_name
                    )
                    if msg:
                        self._corner_advice_type[corner.index] = 'no_trail_brake'
                        return msg

        return ""

    # ── Post feedback: compares this lap vs last lap on the coached metric ──
    def _generate_post_feedback(self, corner: Corner,
                                 ct: Optional[CornerTarget],
                                 driver_trace: LapTrace) -> str:
        """Post-corner feedback. Compares this lap vs last lap on the specific
        metric that was identified in the approach cue. Falls back to vs target
        when no previous lap data is available."""
        # ── Focus Model Gate ──
        if self.lap_focus_entities:
            if corner.index in self.lap_focus_entities:
                pass
            else:
                in_focused_complex = any(
                    -cx.index in self.lap_focus_entities
                    and corner.index in cx.corner_indices
                    for cx in self.complexes
                )
                if not in_focused_complex:
                    return ""

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

        advice_type = self._corner_advice_type.get(corner.index)

        # ── Compare vs previous lap if available ──
        prev_data = self._prev_corner_data.get(corner.index)
        if prev_data and len(prev_data) >= 5:
            prev_trace = LapTrace(points=prev_data)

            if advice_type == 'brake_early' and driver_brake_m:
                prev_brake_m = prev_trace.find_brake_point(corner, search_range=250)
                if prev_brake_m:
                    improvement = driver_brake_m - prev_brake_m           # + = braked later = improved
                    remaining   = ct.target_brake_m - driver_brake_m      # + = still needs to go later
                    msg = self.enhanced_coach.generate_assessment(
                        corner.index, 'brake_early',
                        improvement=improvement, remaining=remaining)
                    if msg:
                        return msg

            elif advice_type == 'apex_slow' and driver_apex:
                prev_apex = prev_trace.get_at_dist(corner.apex_m, window=30)
                if prev_apex:
                    improvement = driver_apex.speed_kph - prev_apex.speed_kph   # + = faster = improved
                    remaining   = ct.target_apex_speed - driver_apex.speed_kph  # + = still slow
                    msg = self.enhanced_coach.generate_assessment(
                        corner.index, 'apex_slow',
                        improvement=improvement, remaining=remaining)
                    if msg:
                        return msg

            elif advice_type == 'exit_slow' and driver_exit:
                prev_exit = prev_trace.get_at_dist(corner.exit_m, window=30)
                if prev_exit:
                    improvement = driver_exit.speed_kph - prev_exit.speed_kph   # + = faster = improved
                    remaining   = ct.target_exit_speed - driver_exit.speed_kph  # + = still slow
                    msg = self.enhanced_coach.generate_assessment(
                        corner.index, 'exit_slow',
                        improvement=improvement, remaining=remaining)
                    if msg:
                        return msg

            elif advice_type == 'no_trail_brake' and driver_apex:
                prev_apex = prev_trace.get_at_dist(corner.apex_m, window=30)
                if prev_apex:
                    improvement = driver_apex.speed_kph - prev_apex.speed_kph   # proxy: apex speed gain
                    remaining   = ct.target_apex_speed - driver_apex.speed_kph
                    msg = self.enhanced_coach.generate_assessment(
                        corner.index, 'no_trail_brake',
                        improvement=improvement, remaining=remaining)
                    if msg:
                        return msg

            elif advice_type == 'apex_early':
                cur_apex_dist  = self._find_apex_dist(driver_trace, corner)
                prev_apex_dist = self._find_apex_dist(prev_trace, corner)
                if cur_apex_dist is not None and prev_apex_dist is not None:
                    improvement = cur_apex_dist - prev_apex_dist          # + = apex later = improved
                    remaining   = corner.apex_m - cur_apex_dist           # + = still early
                    msg = self.enhanced_coach.generate_assessment(
                        corner.index, 'apex_early',
                        improvement=improvement, remaining=max(0.0, remaining))
                    if msg:
                        return msg

            elif advice_type == 'line_wide' and ct and ct.target_trace:
                ref_trace_ct = ct.target_trace
                if ref_trace_ct._spline_dists and driver_trace.has_position_data():
                    drv_pt = driver_trace.get_at_dist(corner.apex_m, window=30)
                    if drv_pt and (abs(drv_pt.world_x) > 0.1 or abs(drv_pt.world_z) > 0.1):
                        cur_dev = ref_trace_ct.get_lateral_deviation(
                            corner.apex_m, drv_pt.world_x, drv_pt.world_z)
                        prev_data_pts = self._prev_corner_data.get(corner.index, [])
                        prev_t = LapTrace(points=prev_data_pts) if len(prev_data_pts) >= 5 else None
                        prev_dev = None
                        if prev_t and prev_t.has_position_data():
                            prev_pt = prev_t.get_at_dist(corner.apex_m, window=30)
                            if prev_pt and (abs(prev_pt.world_x) > 0.1 or abs(prev_pt.world_z) > 0.1):
                                prev_dev = ref_trace_ct.get_lateral_deviation(
                                    corner.apex_m, prev_pt.world_x, prev_pt.world_z)
                        if cur_dev is not None:
                            improvement = (abs(prev_dev) - abs(cur_dev)) if prev_dev is not None else 0.0
                            remaining   = abs(cur_dev)                    # how far still wide
                            msg = self.enhanced_coach.generate_assessment(
                                corner.index, 'line_wide',
                                improvement=improvement, remaining=remaining)
                            if msg:
                                return msg

            else:
                # No specific advice type — use apex speed as general indicator
                if driver_apex:
                    prev_apex = prev_trace.get_at_dist(corner.apex_m, window=30)
                    if prev_apex:
                        improvement = driver_apex.speed_kph - prev_apex.speed_kph
                        remaining   = ct.target_apex_speed - driver_apex.speed_kph
                        if abs(improvement) > 1.0:  # only speak if measurable change
                            msg = self.enhanced_coach.generate_assessment(
                                corner.index, 'apex_slow',
                                improvement=improvement, remaining=remaining)
                            if msg:
                                return msg
            return ""  # prev lap data exists but no message generated — stay silent

        # ── No previous lap data: first-pass assessment vs composite target ──
        if driver_brake_m:
            delta = driver_brake_m - ct.target_brake_m
            if delta < -8:
                self._record_corner_event(corner.index, delta, self.live_dist, 'brake_early')
                msg = self.enhanced_coach.generate_assessment(
                    corner.index, 'brake_early',
                    improvement=0, remaining=abs(delta))
                if msg:
                    return msg

        if driver_apex:
            delta = ct.target_apex_speed - driver_apex.speed_kph
            if delta > 8:
                self._record_corner_event(corner.index, delta, self.live_dist, 'apex_slow')
                msg = self.enhanced_coach.generate_assessment(
                    corner.index, 'apex_slow',
                    improvement=0, remaining=delta)
                if msg:
                    return msg

        if driver_exit:
            delta = ct.target_exit_speed - driver_exit.speed_kph
            if delta > 10:
                self._record_corner_event(corner.index, delta, self.live_dist, 'exit_slow')
                msg = self.enhanced_coach.generate_assessment(
                    corner.index, 'exit_slow',
                    improvement=0, remaining=delta)
                if msg:
                    return msg

        if driver_apex and driver_brake_m:
            apex_brake_pt = driver_trace.get_at_dist(corner.apex_m, window=20)
            if apex_brake_pt and apex_brake_pt.brake_pct < 5:
                brake_pts = [p for p in driver_trace.points
                           if corner.brake_point_m - 20 <= p.dist_m <= corner.brake_point_m + 50]
                if brake_pts and max(p.brake_pct for p in brake_pts) > 60:
                    self._record_corner_event(corner.index, 100, self.live_dist, 'no_trail_brake')
                    remaining = ct.target_apex_speed - driver_apex.speed_kph if ct else 0
                    msg = self.enhanced_coach.generate_assessment(
                        corner.index, 'no_trail_brake',
                        improvement=0, remaining=max(0, remaining))
                    if msg:
                        return msg

        # ── Fallback apex_early / line_wide vs reference (no prev lap) ──
        apex_dist = self._find_apex_dist(driver_trace, corner)
        if apex_dist is not None and apex_dist < corner.apex_m - 25:
            delta = corner.apex_m - apex_dist
            self._record_corner_event(corner.index, delta, self.live_dist, 'apex_early')
            msg = self.enhanced_coach.generate_assessment(
                corner.index, 'apex_early',
                improvement=0, remaining=delta)
            if msg:
                return msg

        if ct and ct.target_trace and ct.target_trace._spline_dists and driver_trace.has_position_data():
            drv_pt = driver_trace.get_at_dist(corner.apex_m, window=30)
            if drv_pt and (abs(drv_pt.world_x) > 0.1 or abs(drv_pt.world_z) > 0.1):
                dev = ct.target_trace.get_lateral_deviation(
                    corner.apex_m, drv_pt.world_x, drv_pt.world_z)
                if dev is not None and abs(dev) > 1.5:
                    self._record_corner_event(corner.index, abs(dev), self.live_dist, 'line_wide')
                    msg = self.enhanced_coach.generate_assessment(
                        corner.index, 'line_wide',
                        improvement=0, remaining=abs(dev))
                    if msg:
                        return msg

        return ""

    # ── ADDED: Complex feedback generation ──
    def _generate_complex_feedback(self, cx: Complex,
                                    driver_trace: LapTrace) -> str:
        """Generate sequence-level feedback for a corner complex."""
        # ── Focus Model Gate ──
        if self.lap_focus_entities:
            # Check if this complex is in focus
            if -cx.index not in self.lap_focus_entities:
                return ""
        
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
            self._record_corner_event(cx.index, min_diff, self.live_dist, 'complex')
            return self.enhanced_coach.generate_instruction(
                cx.index, 'complex_min_speed', complex_name=cx.complex_type
            )
        elif exit_diff > 15:
            self._record_corner_event(cx.index, exit_diff, self.live_dist, 'complex')
            return self.enhanced_coach.generate_instruction(
                cx.index, 'complex_exit_speed', complex_name=cx.complex_type
            )

        return ""

    

    # ─────────────────────────────────────────────────────────────────────────
    # Section Engine Methods
    # ─────────────────────────────────────────────────────────────────────────

    def _update_section_timing(self, cx: Complex, point: TelPoint):
        """Track when the driver enters and exits a section each lap."""
        # Record entry: first point at or beyond section start
        if cx.index not in self._section_enter_time:
            if point.dist_m >= cx.start_m:
                self._section_enter_time[cx.index] = point.timestamp

        # Record exit and compute section time
        if (cx.index in self._section_enter_time
                and cx.index not in self._section_exit_time
                and point.dist_m >= cx.end_m):
            self._section_exit_time[cx.index] = point.timestamp
            section_time = point.timestamp - self._section_enter_time[cx.index]

            if cx.index not in self._section_lap_times:
                self._section_lap_times[cx.index] = deque(maxlen=5)
            self._section_lap_times[cx.index].append(section_time)

            # Update personal best for this section
            if (cx.index not in self._section_best_time
                    or section_time < self._section_best_time[cx.index]):
                self._section_best_time[cx.index] = section_time

            log.debug("Section '%s' time=%.3fs best=%.3fs",
                      cx.name, section_time, self._section_best_time[cx.index])

    def _check_section_approach_cue(self, cx: Complex, point: TelPoint):
        """Fire section briefing ~SECTION_APPROACH_M before section entry."""
        if cx.index in self._section_approach_fired:
            return

        trigger_dist = cx.start_m - SECTION_APPROACH_M
        if abs(point.dist_m - trigger_dist) > APPROACH_WINDOW_M:
            return
        if point.dist_m > cx.start_m:
            return  # Already inside — missed window

        # Focus model gate: only coach in-focus sections
        if self.lap_focus_entities and -cx.index not in self.lap_focus_entities:
            return

        self._section_approach_fired.add(cx.index)

        bottleneck = self._get_section_bottleneck(cx)
        msg = self.enhanced_coach.generate_section_instruction(
            cx.index,
            cx.complex_type,
            complex_name=cx.name,
            bottleneck_corner_idx=bottleneck,
        )
        if msg:
            log.info("🟢 Section approach: '%s' bottleneck=T%d", cx.name, bottleneck)
            log.info("🗣 Generated coaching: %s", msg)
            self._speak(msg, source=f"section_approach_{cx.index}", priority=True)
            self._notify()

    def _check_section_post_cue(self, cx: Complex, point: TelPoint):
        """Fire section time assessment after the final exit."""
        if cx.index in self._section_post_fired:
            return
        if cx.index not in self._section_approach_fired:
            return  # No briefing this lap -> no assessment

        post_dist = cx.end_m + POST_CORNER_M
        if abs(point.dist_m - post_dist) > APPROACH_WINDOW_M:
            return

        self._section_post_fired.add(cx.index)

        history = self._section_lap_times.get(cx.index)
        if not history or len(history) < 2:
            return  # First completed pass — no comparison data yet

        times = list(history)
        this_time = times[-1]
        prev_time = times[-2]
        best_time = self._section_best_time.get(cx.index, this_time)

        improvement = prev_time - this_time       # positive = faster this lap
        remaining   = this_time - best_time       # positive = still off personal best

        msg = self.enhanced_coach.generate_section_assessment(
            cx.index, improvement, remaining
        )
        if msg:
            log.info("🟢 Section post: '%s' improvement=%.3fs remaining=%.3fs",
                     cx.name, improvement, remaining)
            log.info("🗣 Generated coaching: %s", msg)
            self._speak(msg, source=f"section_post_{cx.index}", priority=True)
            self._notify()

    def _get_section_bottleneck(self, cx: Complex) -> int:
        """
        Return the corner_idx with the greatest apex-speed deficit vs reference
        within this complex. Returns 0 if data is unavailable.
        """
        if not self.composite:
            return 0
        worst_idx = 0
        worst_delta = 0.0
        for corner in cx.corners:
            ct = self.composite.targets.get(corner.index)
            if not ct or ct.target_apex_speed <= 0:
                continue
            prev_data = self._prev_corner_data.get(corner.index, [])
            if not prev_data:
                continue
            prev_trace = LapTrace(points=prev_data)
            apex_pt = prev_trace.get_at_dist(corner.apex_m, window=30)
            if apex_pt:
                delta = ct.target_apex_speed - apex_pt.speed_kph
                if delta > worst_delta:
                    worst_delta = delta
                    worst_idx = corner.index
        return worst_idx

    def _escalate_feedback(self, prefix: str, tag: str, base_msg: str,
                            count: int, corner: Corner) -> str:
        # ... [keep your existing code] ...
        pass

            # ── Strategic Lap Focus Model ──
    
    def is_entity_in_focus(self, entity_idx: int) -> bool:
        """Check if a corner or complex is in the current lap focus."""
        return entity_idx in self.lap_focus_entities
    
    def compute_lap_focus(self):
        """
        Compute which entities (corners/complexes) to focus on for the next lap.
        Uses PURE SECTOR DELTA RANKING (not heuristic estimation).
        
        Algorithm:
        1. Use actual sector time deltas from sector_results
        2. Map sectors to corners/complexes
        3. Apply persistence, spacing, and limit constraints
        """
        if not self.sector_results:
            return
        
        # 1. Calculate time loss per entity using ACTUAL SECTOR DELTAS
        self.entity_time_loss.clear()
        
        # Map sector results to entities
        for result in self.sector_results:
            sector_idx = result.sector_idx
            
            # Get sector time delta (player vs target)
            time_loss = result.delta_to_target if result.delta_to_target > 0 else 0
            
            # Skip if no significant time loss
            if time_loss < FOCUS_PERSISTENCE_THRESHOLD_S:
                continue
            
            # Find which entity this sector corresponds to
            # First check if it's a complex
            entity_found = False
            for cx in self.complexes:
                # Check if sector corresponds to this complex
                # (Assuming sector index matches complex index for now)
                if sector_idx == cx.index:
                    # Use negative index for complexes
                    self.entity_time_loss[-sector_idx] = time_loss
                    entity_found = True
                    break
            
            # If not a complex, check if it's a corner
            if not entity_found:
                # Check if sector corresponds to a corner
                # (Assuming 1:1 mapping between sectors and corners for now)
                for corner in self.corners:
                    if corner.index == sector_idx:
                        self.entity_time_loss[sector_idx] = time_loss
                        break
        
        if not self.entity_time_loss:
            self.lap_focus_entities.clear()
            return
        
        # 2. Sort entities by time loss (descending) - PURE SECTOR DELTA RANKING
        sorted_entities = sorted(
            self.entity_time_loss.items(),
            key=lambda x: x[1],  # Sort by actual sector time delta
            reverse=True
        )
        
        # 3. Apply persistence: keep entities from previous focus if still losing time
        candidate_entities = set()
        
        for entity_idx, time_loss in sorted_entities:
            # Keep if still losing significant time
            if entity_idx in self.last_focus_entities and time_loss > FOCUS_PERSISTENCE_THRESHOLD_S:
                candidate_entities.add(entity_idx)
            
            # Add new entities with significant time loss
            elif entity_idx not in self.last_focus_entities and time_loss > FOCUS_PERSISTENCE_THRESHOLD_S:
                candidate_entities.add(entity_idx)
            
            # Stop if we have enough candidates
            if len(candidate_entities) >= MAX_FOCUS_ENTITIES * 2:  # Start with more, then filter
                break
        
        # 4. Apply minimum spacing constraint
        final_entities = set()
        
        # Convert entity indices to their approximate track positions
        entity_positions = []
        for entity_idx in candidate_entities:
            if entity_idx > 0:  # Corner
                corner = next((c for c in self.corners if c.index == entity_idx), None)
                if corner:
                    entity_positions.append((entity_idx, corner.apex_m))
            else:  # Complex (negative index)
                cx = next((c for c in self.complexes if c.index == -entity_idx), None)
                if cx:
                    entity_positions.append((entity_idx, (cx.start_m + cx.end_m) / 2))
        
        # Sort by track position
        entity_positions.sort(key=lambda x: x[1])
        
        for entity_idx, position in entity_positions:
            # Check spacing with already selected entities
            too_close = False
            for selected_idx, selected_pos in [(idx, pos) for idx, pos in entity_positions if idx in final_entities]:
                if abs(position - selected_pos) < MIN_SPACING_M:
                    too_close = True
                    break
            
            if not too_close:
                final_entities.add(entity_idx)
                
            if len(final_entities) >= MAX_FOCUS_ENTITIES:
                break
        
        # 5. Update focus sets
        self.last_focus_entities = self.lap_focus_entities.copy()
        self.lap_focus_entities = final_entities
        
        # 6. Log the focus selection
        if self.lap_focus_entities:
            focus_desc = []
            for entity_idx in self.lap_focus_entities:
                if entity_idx > 0:
                    focus_desc.append(f"C{entity_idx}")
                else:
                    cx = next((c for c in self.complexes if c.index == -entity_idx), None)
                    if cx:
                        corners_str = ','.join(str(i) for i in cx.corner_indices)
                        focus_desc.append(f"Complex {cx.complex_type} (C{corners_str})")
            
            log.info("🎯 Lap focus entities (sector delta ranking): %s", ", ".join(focus_desc))
            
            # Announce focus for the next lap
            if len(focus_desc) == 1:
                self._speak(f"Focus on {focus_desc[0]} this lap.", source="focus_model")
            elif len(focus_desc) > 1:
                self._speak(f"Focus on {', '.join(focus_desc[:-1])} and {focus_desc[-1]} this lap.", source="focus_model")
    
        # Note: Heuristic time estimation methods removed in favor of pure sector delta ranking
    
    def _record_corner_event(self, corner_idx: int, delta: float, dist: float, issue_type: str):
        """Record a corner delta event for later ranking."""
        self.corner_events_this_lap.append({
            'corner_idx': corner_idx,
            'delta': delta,
            'dist': dist,
            'issue_type': issue_type,
            'timestamp': time.time()
        })
        log.debug("📝 Recorded corner event: C%d delta=%.1f dist=%.0f issue=%s",
                  corner_idx, delta, dist, issue_type)

    def _can_speak(self, corner_idx: int, source: str, dist: float) -> bool:
        """
        Speech gate: hard budget cap only.
        3 focus entities × (approach + post) = max 6 coaching messages per lap.
        Approach/post dedup is handled upstream by _approach_fired/_post_fired sets.
        """
        if len(self.speeches_this_lap) >= self.speech_budget_max:
            log.info("🗣️ Suppressed: budget full (%d of %d)",
                     len(self.speeches_this_lap), self.speech_budget_max)
            return False
        return True

    def _speak(self, text: str, source: str, priority: bool = False):
        """
        Structured logging wrapper for all speech with gate.
        Logs WHO triggered speech, FROM WHICH METHOD, and CURRENT STATE.
        """
        # Whitelist of non-corner sources that bypass gate
        non_corner_sources = {
            'start_no_corners', 'start_coaching', 'stop',
            'lap_completion_learning', 'lap_completion_pb', 'lap_completion_delta',
            'lap_completion_all_active', 'focus_model', 'corner_promotion'
        }
        
        corner_idx = None
        # Try to parse corner index from source
        import re
        # pattern: approach_cue_C1, post_feedback_C2, corner_promotion_C3, complex_feedback_C4 (where 4 is complex index)
        match = re.search(r'_C(\d+)', source)
        if match:
            corner_idx = int(match.group(1))
        
        # Determine if this is a corner-related speech that should be gated
        is_corner_speech = corner_idx is not None and source not in non_corner_sources
        
        if is_corner_speech:
            # Apply speech gate
            if not self._can_speak(corner_idx, source, self.live_dist):
                log.info("🗣️ SPEECH BLOCKED | source=%s | corner=%d | dist=%.0f",
                         source, corner_idx, self.live_dist)
                return  # Suppress speech
        
        # Log speech
        log.info(
            "🗣 SPEECH | source=%s | phase=%s | lap=%d | speed=%.1f | dist=%.0f | text=%s",
            source,
            self.phase,
            self.lap_count,
            self.live_speed,
            self.live_dist,
            text,
        )
        
        # Record speech for budget tracking
        if is_corner_speech:
            is_complex_speech = 'complex_feedback' in source
            entity_id = self._get_entity_id(corner_idx, is_complex=is_complex_speech)
            self.speeches_this_lap.append({
                'dist': self.live_dist,
                'source': source,
                'corner_idx': corner_idx,
                'timestamp': time.time()
            })
            self.entities_spoken_this_lap.add(entity_id)
        
        # Deliver speech
        if priority:
            self.speaker.say_priority(text)
        else:
            self.speaker.say(text)
    
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
            ],
            'improved_brake_post': [
                "C{idx}: {delta:.0f}m later on the brakes. That's it.",
                "Better entry at {idx}. Braking later. Keep pushing that point.",
                "C{idx}: brake point improved by {delta:.0f}m. Hold that confidence.",
                "{idx}: later braking. Carry that forward.",
                "C{idx}: better entry. That's the improvement we wanted."
            ],
            'improved_apex_post': [
                "C{idx}: {delta:.0f}kph faster at the apex. Good.",
                "Better through {idx}. {delta:.0f}kph up at the apex.",
                "C{idx}: apex speed up {delta:.0f}kph. That's the improvement.",
                "{idx}: carrying more speed. Keep that commitment.",
                "C{idx}: {delta:.0f}kph gained at the apex. You found the grip."
            ],
            'improved_exit_post': [
                "C{idx}: {delta:.0f}kph better on exit. Good.",
                "Exit improved at {idx}. {delta:.0f}kph faster.",
                "C{idx}: better exit speed. Keep hitting that apex.",
                "{idx}: exit up {delta:.0f}kph. Apex is working.",
                "C{idx}: good exit. That's exactly what we needed."
            ],
            'apex_early_pre': [
                "C{idx}: apex too early, {delta:.0f}m ahead of the sweet spot. Wait for the exit to open.",
                "Corner {idx}: you're turning in too soon. Hold the outside {delta:.0f}m longer.",
                "Into {idx}: early apex. Delay turn-in, let the corner come to you.",
                "C{idx}: turning too early. Hold wider on entry, apex later.",
                "Corner {idx}: early apex costing exit speed. Wait, then commit."
            ],
            'apex_early_post': [
                "C{idx}: still apexing {delta:.0f}m early. Hold the outside longer next lap.",
                "Early apex at {idx} again. Delay turn-in, wait for the exit to open.",
                "{idx}: too early on apex. Drive past the early apex point, then turn.",
                "C{idx}: turning in before the apex. Hold it wider, later.",
                "Corner {idx}: early apex. Stay on the outside until the road straightens."
            ],
            'improved_apex_early_post': [
                "C{idx}: apex {delta:.0f}m later. Better. Keep pushing it back.",
                "Better timing at {idx}. Apex is later, exit will open up.",
                "C{idx}: later apex this lap. That's the improvement we needed.",
                "{idx}: held the outside longer. Good. Now nail the exit.",
                "C{idx}: apex timing improved. Keep that patience on entry."
            ],
            'line_wide_pre': [
                "C{idx}: {delta:.1f}m off the reference at apex. Use more track, clip the inside.",
                "Corner {idx}: missing the apex. Get tighter, use the full width.",
                "Into {idx}: you're not using the track. More width on entry, clip the kerb.",
                "C{idx}: wide at apex. Drive to the edge, use every metre.",
                "Corner {idx}: off the line. Entry wide, apex tight, exit wide."
            ],
            'line_wide_post': [
                "C{idx}: {delta:.1f}m from the reference line at apex. Use more track.",
                "Off line at {idx}. Get the front to the kerb at apex.",
                "{idx}: missing the inside. Use the full track width.",
                "C{idx}: not clipping the apex. More commitment to the inside.",
                "Corner {idx}: you're leaving track on the table. Clip the apex."
            ],
            'improved_line_post': [
                "C{idx}: better line. Closer to the reference at apex.",
                "Line improved at {idx}. Keep committing to the apex.",
                "C{idx}: tighter apex this lap. That's the right direction.",
                "{idx}: line is cleaner. Keep using the full track.",
                "C{idx}: better through apex. That's the line."
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





