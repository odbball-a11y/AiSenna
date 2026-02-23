# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import time
from pathlib import Path
import csv
import logging
from dataclasses import dataclass, field

from senna_ai.telemetry.models import TelPoint
from senna_ai.data.detect import detect_car_class
from senna_ai.coaching.coaching_constants import MIN_SPEED_MPS

log = logging.getLogger(__name__)




# ═══════════════════════════════════════════════════════════════════════════
# Live Opponent Tracker — captures AI telemetry and saves fast laps
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class _LiveOppState:
    """Tracking state for a single opponent vehicle."""
    scoring_idx: int
    telem_idx: int
    mID: int
    driver_name: str
    car_name: str              # mVehicleName (team/entry name)
    vehicle_class: str = ""    # mVehicleClass (e.g. "LMP2", "LMH", "LMGT3")
    last_dist: float = 0.0
    lap_points: list = field(default_factory=list)
    lap_start_time: float = 0.0
    laps_completed: int = 0
    synced: bool = False


class OpponentTracker:
    """
    Tracks all non-player vehicles in the session.
    When an opponent completes a lap, if it's faster than our threshold,
    save it as a CSV to the opponent_laps folder — same format as existing CSVs.
    """

    def __init__(self, save_folder: str, track_name: str = "", car_filter: str = "",
                 on_new_lap=None):
        self.save_folder = save_folder
        self.track_name = track_name
        self.car_filter = car_filter  # Unused for now — save all cars
        self.on_new_lap = on_new_lap  # Callback: on_new_lap(csv_path)

        self._opponents: dict[int, _LiveOppState] = {}  # keyed by mID
        self._track_length: float = 0.0
        self._fastest_saved: float = 9999.0  # Don't save if slower than this
        self._save_count: int = 0

        os.makedirs(save_folder, exist_ok=True)

    def update(self, lmumem, player_id: int):
        """Called every tick from the reader loop. Scans all vehicles."""
        try:
            scoring = lmumem.data.scoring
            num_veh = scoring.scoringInfo.mNumVehicles

            # Track length — use the maximum mLapDist seen across all vehicles
            # as a reliable measure (scoringInfo.mLapDist can be wrong)
            for i in range(num_veh):
                try:
                    d = scoring.vehScoringInfo[i].mLapDist
                    if d and d > self._track_length:
                        self._track_length = d
                except Exception:
                    pass

            if not self.track_name:
                try:
                    self.track_name = scoring.scoringInfo.mTrackName.decode(
                        errors="ignore"
                    ).strip("\x00")
                except Exception:
                    pass

            seen_ids = set()

            for i in range(num_veh):
                try:
                    sv = scoring.vehScoringInfo[i]
                    mid = sv.mID
                    if mid == player_id:
                        continue  # Skip player

                    seen_ids.add(mid)
                    dist = sv.mLapDist

                    # ── New opponent? ──
                    if mid not in self._opponents:
                        # Find telemetry index
                        telem_idx = None
                        for ti in range(128):
                            try:
                                tv = lmumem.data.telemetry.telemInfo[ti]
                                if tv.mID == mid:
                                    telem_idx = ti
                                    break
                            except Exception:
                                break

                        if telem_idx is None:
                            continue

                        driver = sv.mDriverName.decode(errors="ignore").strip("\x00")
                        car = lmumem.data.telemetry.telemInfo[telem_idx].mVehicleName.decode(
                            errors="ignore"
                        ).strip("\x00")

                        # Get vehicle class from scoring (e.g. "LMP2", "LMH", "LMGT3")
                        veh_class = ""
                        try:
                            veh_class = sv.mVehicleClass.decode(errors="ignore").strip("\x00")
                        except Exception:
                            pass

                        self._opponents[mid] = _LiveOppState(
                            scoring_idx=i, telem_idx=telem_idx, mID=mid,
                            driver_name=driver, car_name=car,
                            vehicle_class=veh_class,
                            last_dist=dist, lap_start_time=time.time(),
                        )
                        cls_tag = detect_car_class(car, veh_class)
                        log.info("👁️ Tracking opponent: %s (%s) [%s/%s] mID=%d",
                                 driver, car, veh_class, cls_tag, mid)
                        continue

                    # ── Existing opponent: record telemetry ──
                    opp = self._opponents[mid]
                    opp.scoring_idx = i  # May shift

                    # Read telemetry
                    try:
                        tv = lmumem.data.telemetry.telemInfo[opp.telem_idx]
                        vel = tv.mLocalVel
                        speed_mps = (vel.x**2 + vel.y**2 + vel.z**2)**0.5

                        if speed_mps > MIN_SPEED_MPS:
                            # World position
                            wx = wy = wz = 0.0
                            try:
                                pos = tv.mPos
                                wx, wy, wz = pos.x, pos.y, pos.z
                            except Exception:
                                pass

                            opp.lap_points.append(TelPoint(
                                dist_m=dist,
                                speed_kph=speed_mps * 3.6,
                                throttle_pct=tv.mFilteredThrottle * 100,
                                brake_pct=tv.mFilteredBrake * 100,
                                steer_pct=tv.mFilteredSteering * 100,
                                gear=tv.mGear,
                                timestamp=time.time(),
                                world_x=wx, world_y=wy, world_z=wz,
                            ))
                    except Exception:
                        pass

                    # ── Detect lap crossing (distance wraps from near end to near start) ──
                    # Must be a genuine full-lap wrap, not a pit stop or reset.
                    # The drop must be >80% of track length (e.g. 4800->100 on a 4900m track)
                    # and the car must have been in the last 20% of the track.
                    dist_drop = opp.last_dist - dist
                    crossed = (
                        self._track_length > 1000
                        and dist_drop > self._track_length * 0.8
                        and opp.last_dist > self._track_length * 0.85
                        and dist < self._track_length * 0.15
                    )
                    opp.last_dist = dist

                    if crossed:
                        if not opp.synced:
                            # First crossing — this was a partial lap from mid-session join.
                            # Discard it and start clean.
                            opp.synced = True
                            opp.lap_points = []
                            opp.lap_start_time = time.time()
                            log.info(
                                "🔄 %s synced at start/finish (discarded partial lap)",
                                opp.driver_name[:20],
                            )
                            continue

                        lap_time = time.time() - opp.lap_start_time
                        opp.laps_completed += 1
                        points = opp.lap_points

                        # Check distance coverage — points should span most of the track
                        if points:
                            dists = [p.dist_m for p in points]
                            coverage = max(dists) - min(dists)
                        else:
                            coverage = 0

                        # Validate:
                        #   - Lap time reasonable (at least track_length/100 seconds ≈ 50s for 5km)
                        #   - Enough data points (at least 10 per km of track)
                        #   - Distance coverage > 75% of track length (not a partial lap)
                        min_reasonable_time = self._track_length / 100.0  # ~50s for 5km
                        min_points = max(200, int(self._track_length / 500) * 20)
                        min_coverage = self._track_length * 0.75

                        if (lap_time > min_reasonable_time
                                and len(points) > min_points
                                and coverage > min_coverage):
                            self._save_lap(opp, points, lap_time)
                        else:
                            log.info(
                                "❌ Rejected lap: %s %.1fs pts=%d coverage=%.0f/%.0fm "
                                "(need >%.0fs, >%d pts, >%.0fm)",
                                opp.driver_name[:15], lap_time, len(points),
                                coverage, self._track_length,
                                min_reasonable_time, min_points, min_coverage,
                            )

                        # Reset for next lap
                        opp.lap_points = []
                        opp.lap_start_time = time.time()

                except Exception:
                    continue

            # Remove departed opponents
            departed = set(self._opponents.keys()) - seen_ids
            for mid in departed:
                opp = self._opponents.pop(mid)
                log.info("👋 Opponent departed: %s", opp.driver_name)

        except Exception as e:
            log.debug("OpponentTracker error: %s", e)

    def _save_lap(self, opp: _LiveOppState, points: list[TelPoint], lap_time: float):
        """Save a completed opponent lap as CSV in the same format."""
        self._save_count += 1

        # Generate filename matching existing convention
        track_slug = self.track_name.lower().replace(" ", "_").replace("'", "")
        # Sanitise for filename — ASCII only
        driver_slug = "".join(
            c for c in opp.driver_name[:3].upper() if c.isalnum()
        ) or "UNK"
        timestamp = time.strftime("%Y-%m-%d_%H%M%S")
        fname = (
            f"{track_slug}_{lap_time:.3f}s_{driver_slug}"
            f"_L{opp.laps_completed}_{timestamp}_live.csv"
        )
        fpath = os.path.join(self.save_folder, fname)

        try:
            # Build a car name that includes the class for reliable detection
            # e.g. "IDEC Sport 2025 #18:LM (LMP2)" or "AF Corse 2025 #183:LM (LMH)"
            car_with_class = opp.car_name
            if opp.vehicle_class:
                car_with_class = f"{opp.car_name} ({opp.vehicle_class})"

            with open(fpath, "w", newline="", encoding="utf-8") as f:
                # Row 0: format marker
                f.write(f"opponent,v3,{opp.driver_name},0,{int(time.time()*1000)}\n")
                # Row 1-2: metadata
                f.write("Game,version,date,track,car,event,laptime [s],S1 [s],S2 [s],S3 [s],S4+ [s]\n")
                f.write(f"LMU,1.2,{time.strftime('%Y-%m-%d %H:%M:%S')},"
                        f"{self.track_name},{car_with_class},Live,{lap_time:.3f},0,0,0\n")
                # Row 3-4: extended metadata
                f.write("Tracklen [m],TotalLaps\n")
                f.write(f"{self._track_length:.1f},{opp.laps_completed}\n")
                # Row 5-6: empty
                f.write(",\n,\n")
                # Row 7: telemetry header
                f.write("lapdistance [m],speed [m/s],throttle [%],brake [%],"
                        "steer [%],gear [int],world_x [m],world_y [m],world_z [m]\n")
                # Data rows
                for p in points:
                    f.write(f"{p.dist_m:.1f},{p.speed_kph/3.6:.2f},"
                            f"{p.throttle_pct:.1f},{p.brake_pct:.1f},"
                            f"{p.steer_pct:.1f},{p.gear},"
                            f"{p.world_x:.3f},{p.world_y:.3f},{p.world_z:.3f}\n")

            self._fastest_saved = min(self._fastest_saved, lap_time)
            log.info(
                "💾 Saved opponent lap: %s (%.3fs, %d pts) -> %s",
                opp.driver_name, lap_time, len(points), fname,
            )

            # Notify the app to hot-reload
            if self.on_new_lap:
                self.on_new_lap(fpath)

        except Exception as e:
            log.warning("Failed to save opponent lap: %s", e)

    @property
    def opponent_count(self) -> int:
        return len(self._opponents)

    @property
    def saved_count(self) -> int:
        return self._save_count



