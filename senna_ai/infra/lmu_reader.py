from __future__ import annotations

import os
import threading
import time
import logging
from typing import Optional, TYPE_CHECKING

from senna_ai.data.opponent_tracker import OpponentTracker
from senna_ai.data.detect import detect_car_class
from senna_ai.infra.pyLMUSharedMemory.lmu_data import LMUConstants, LMUObjectOut
from senna_ai.infra.pyLMUSharedMemory.lmu_mmap import MMapControl

if TYPE_CHECKING:
    from senna_ai.coaching.engine import CoachingEngine

log = logging.getLogger(__name__)

# Shared memory polling rate (Hz)
from senna_ai.coaching.coaching_constants import POLL_HZ


# ═══════════════════════════════════════════════════════════════════════════
# LMU Shared Memory Reader — captures player + live opponents
# ═══════════════════════════════════════════════════════════════════════════
class LMUReader:
    """Reads telemetry from LMU shared memory in a background thread."""

    def __init__(
        self,
        engine: "CoachingEngine",
        on_telemetry=None,
        save_folder: str = "",
        on_new_opponent_lap=None,
    ):
        self.engine = engine
        self.on_telemetry = on_telemetry
        self.on_new_opponent_lap = on_new_opponent_lap
        self.save_folder = save_folder

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.connected = False
        self.current_track = ""
        self.current_car = ""
        self.player_car_class = ""
        self.opp_tracker: Optional[OpponentTracker] = None

    # ───────────────────────────────────────────────

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    # ───────────────────────────────────────────────

    def _run(self):
        try:
            lmumem = MMapControl(
                LMUConstants.LMU_SHARED_MEMORY_FILE,
                LMUObjectOut,
            )
            lmumem.create(access_mode=1)
            self.connected = True
            log.info("Connected to LMU shared memory")

        except Exception as e:
            log.error("Failed to connect to LMU: %s", e)
            self.connected = False
            return

        player_telem_idx = None
        player_scoring_idx = None
        player_id = None
        find_attempts = 0

        try:
            while not self._stop.is_set():

                try:
                    lmumem.update()
                except Exception:
                    time.sleep(0.1)
                    continue

                scoring = lmumem.data.scoring

                # ─────────────────────────────────────
                # Find player vehicle
                # ─────────────────────────────────────
                if player_scoring_idx is None:
                    find_attempts += 1

                    try:
                        num_veh = scoring.scoringInfo.mNumVehicles

                        if find_attempts % 100 == 1:
                            log.info("Searching for player among %d vehicles...", num_veh)

                        for i in range(num_veh):
                            sv = scoring.vehScoringInfo[i]

                            if sv.mIsPlayer:
                                player_scoring_idx = i
                                player_id = sv.mID

                                driver = sv.mDriverName.decode(errors="ignore").strip("\x00")

                                veh_class = ""
                                try:
                                    veh_class = sv.mVehicleClass.decode(errors="ignore").strip("\x00")
                                except Exception:
                                    pass

                                log.info(
                                    "Found player: '%s' at scoring[%d], mID=%d, class='%s'",
                                    driver,
                                    i,
                                    player_id,
                                    veh_class,
                                )

                                self.player_car_class = veh_class
                                break

                    except Exception as e:
                        if find_attempts % 100 == 1:
                            log.warning("Scoring error: %s", e)

                        time.sleep(0.2)
                        continue

                if player_scoring_idx is None:
                    time.sleep(0.1)
                    continue

                # ─────────────────────────────────────
                # Match telemetry index
                # ─────────────────────────────────────
                if player_telem_idx is None:
                    try:
                        for i in range(128):
                            tv = lmumem.data.telemetry.telemInfo[i]
                            if tv.mID == player_id:
                                player_telem_idx = i
                                car_name = tv.mVehicleName.decode(errors="ignore").strip("\x00")

                                log.info(
                                    "Matched telemetry[%d] for player (mID=%d, %s)",
                                    i,
                                    player_id,
                                    car_name,
                                )
                                break
                    except Exception:
                        pass

                    if player_telem_idx is None:
                        time.sleep(0.5)
                        continue

                # ─────────────────────────────────────
                # Read telemetry
                # ─────────────────────────────────────
                veh = lmumem.data.telemetry.telemInfo[player_telem_idx]

                throttle = veh.mFilteredThrottle
                brake = veh.mFilteredBrake
                steer = veh.mFilteredSteering
                gear = veh.mGear

                vel = veh.mLocalVel
                speed_mps = (vel.x ** 2 + vel.y ** 2 + vel.z ** 2) ** 0.5
                speed_kph = speed_mps * 3.6

                car_name = veh.mVehicleName.decode(errors="ignore").strip("\x00")

                if car_name:
                    self.current_car = car_name
                    self.engine.current_car = car_name
                    self.engine.current_car_class = detect_car_class(
                        car_name,
                        self.player_car_class,
                    )

                try:
                    track = scoring.scoringInfo.mTrackName.decode(errors="ignore").strip("\x00")
                    if track:
                        self.current_track = track
                        self.engine.current_track = track
                except Exception:
                    pass

                lap_dist = 0.0
                try:
                    sv = scoring.vehScoringInfo[player_scoring_idx]
                    lap_dist = sv.mLapDist
                except Exception:
                    pass

                world_x = world_y = world_z = 0.0
                try:
                    pos = veh.mPos
                    world_x, world_y, world_z = pos.x, pos.y, pos.z
                except Exception:
                    pass

                # Feed coaching engine
                self.engine.feed(
                    dist_m=lap_dist,
                    speed_kph=speed_kph,
                    speed_mps=speed_mps,
                    throttle=throttle,
                    brake=brake,
                    steer=steer,
                    gear=gear,
                    world_x=world_x,
                    world_y=world_y,
                    world_z=world_z,
                )

                # ─────────────────────────────────────
                # Track opponents
                # ─────────────────────────────────────
                if self.opp_tracker is None and self.current_track:

                    base_dir = os.path.abspath(
                        os.path.join(os.path.dirname(__file__), "..")
                    )

                    opponent_dir = os.path.join(
                        base_dir,
                        "opponent_laps",
                        self.current_track,
                    )

                    self.opp_tracker = OpponentTracker(
                        save_folder=opponent_dir,
                        track_name=self.current_track,
                        on_new_lap=self.on_new_opponent_lap,
                    )

                    log.info("Opponent tracker started (saving to %s)", opponent_dir)

                if self.opp_tracker:
                    self.opp_tracker.update(lmumem, player_id)

                if self.on_telemetry:
                    self.on_telemetry(
                        lap_dist,
                        speed_kph,
                        throttle,
                        brake,
                        gear,
                    )

                time.sleep(1.0 / POLL_HZ)

        finally:
            try:
                lmumem.close()
            except Exception:
                pass
