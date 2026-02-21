from __future__ import annotations
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

import time
import logging
from typing import List, Optional

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
        self.force_model = ForceStageModel()
        self.complexes: list[Complex] = []
        self.complex_map: dict[int, Complex] = {}
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

        # Per-corner issue history
        self._issue_history: dict[tuple[int, str], int] = {}
        self._last_feedback: dict[int, str] = {}
        
        # Enhanced coaching
        self.enhanced_coach = EnhancedCoachingGenerator()
        
        # Geometric reference line
        self.reference_line: dict[float, tuple[float, float]] = {}
        
        # FOCUS TURN COACHING SYSTEM
        self.focus_turn_count = 1  # Default, can be changed via UI slider (1-3)
        self.focus_turns: list[int] = []  # Turn indices selected for focused coaching
        self.turn_focus_data: dict[int, dict] = {}  # per-turn correction data
        self.previous_lap_turn_deltas: dict[int, float] = {}  # delta_to_target from previous lap
        self.last_spoken_time: float = 0.0  # for cooldown tracking
        self.last_cue_spoken: dict[int, float] = {}  # turn_id -> timestamp when cue spoken this lap
        self.last_feedback_spoken: dict[int, float] = {}  # turn_id -> timestamp when feedback spoken this lap
        self.turn_phrase_rotation: dict[str, int] = {}  # for phrase variation

    # ... [rest of the class methods would go here] ...

# ═══════════════════════════════════════════════════════════════════════════
# ENHANCED COACHING GENERATOR
# ═══════════════════════════════════════════════════════════════════════════
class EnhancedCoachingGenerator:
    def __init__(self):
        self.coaching_history = {}
        self._init_phrases()
    
    def _init_phrases(self):
        self.phrases = {
            'brake_early_pre': [
                "Corner {idx}: brake {delta:.0f}m later. Look further ahead, squeeze don't stamp.",
                "C{idx}: you're braking early. Move your marker {delta:.0f}m later.",
                "Into {idx}, brake {delta:.0f}m later than you think. Trust the car.",
                "Corner {idx} approaching: brake point {delta:.0f}m too early. Later marker, commit.",
                "C{idx}: early brakes. Pick a later board, squeeze progressively."
            ],
            # ... [other phrases] ...
        }
    
    def generate_pre(self, corner_idx, issue_type, delta=0, value=0, complex_name="", corners=""):
        key = f"{issue_type}_pre"
        if key not in self.phrases:
            return None
        
        history_key = f"{corner_idx}_{issue_type}_pre"
        used_idx = self.coaching_history.get(history_key, -1)
        next_idx = (used_idx + 1) % len(self.phrases[key])
        self.coaching_history[history_key] = next_idx
        
        phrase = self.phrases[key][next_idx]
        
        if complex_name:
            return phrase.format(idx=corner_idx, delta=abs(delta), value=abs(value), name=complex_name, corners=corners)
        else:
            return phrase.format(idx=corner_idx, delta=abs(delta))
    
    def generate_post(self, corner_idx, issue_type, delta=0, value=0, complex_name="", corners=""):
        key = f"{issue_type}_post"
        if key not in self.phrases:
            return None
        
        history_key = f"{corner_idx}_{issue_type}_post"
        used_idx = self.coaching_history.get(history_key, -1)
        next_idx = (used_idx + 1) % len(self.phrases[key])
        self.coaching_history[history_key] = next_idx
        
        phrase = self.phrases[key][next_idx]
        
        if complex_name:
            return phrase.format(idx=corner_idx, delta=abs(delta), value=abs(value), name=complex_name, corners=corners)
        else:
            return phrase.format(idx=corner_idx, delta=abs(delta))