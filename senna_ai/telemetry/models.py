# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import math
import logging
from dataclasses import dataclass, field
from typing import Optional, List, TYPE_CHECKING

from senna_ai.data.detect import detect_car_class

if TYPE_CHECKING:
    from senna_ai.track.corner_detection import Corner

log = logging.getLogger(__name__)

# Import constant for find_brake_point — use a default if not available yet
_BRAKE_THRESHOLD: float = 8.0
try:
    from senna_ai.coaching.coaching_constants import BRAKE_THRESHOLD as _BT
    _BRAKE_THRESHOLD = _BT
except ImportError:
    pass


# ═══════════════════════════════════════════════════════════════════════════
# Telemetry Data Models
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class TelPoint:
    """A single telemetry sample."""
    dist_m: float
    speed_kph: float
    throttle_pct: float
    brake_pct: float
    steer_pct: float
    gear: int
    timestamp: float = 0.0
    world_x: float = 0.0
    world_y: float = 0.0
    world_z: float = 0.0


@dataclass
class LapTrace:
    """A full lap of telemetry, indexed by distance."""
    points: List[TelPoint] = field(default_factory=list)
    lap_time: float = 0.0

    _spline_dists: List[float] = field(default_factory=list, repr=False)
    _spline_x: List[float] = field(default_factory=list, repr=False)
    _spline_z: List[float] = field(default_factory=list, repr=False)

    # ─────────────────────────────────────────────

    def get_at_dist(self, dist_m: float, window: float = 15.0) -> Optional[TelPoint]:
        best = None
        best_delta = window
        for p in self.points:
            d = abs(p.dist_m - dist_m)
            if d < best_delta:
                best = p
                best_delta = d
        return best

    # ─────────────────────────────────────────────

    def find_brake_point(self, corner: Corner, search_range: float = 200.0) -> Optional[float]:
        """Find where the driver actually started braking near a corner."""
        search_start = corner.brake_point_m - search_range
        search_end = corner.brake_point_m + search_range
        for p in self.points:
            if search_start <= p.dist_m <= search_end and p.brake_pct > _BRAKE_THRESHOLD:
                return p.dist_m
        return None

    # ─────────────────────────────────────────────

    def get_corner_time(self, corner: Corner) -> Optional[float]:
        """Estimate time through a corner zone (brake point to exit)."""
        points_in_zone = [p for p in self.points
                          if corner.brake_point_m - 50 <= p.dist_m <= corner.exit_m + 50]
        if len(points_in_zone) < 2:
            return None
        return points_in_zone[-1].timestamp - points_in_zone[0].timestamp

    # ─────────────────────────────────────────────

    def get_corner_slice(self, corner: Corner, margin: float = 50.0) -> List[TelPoint]:
        """Get all points within a corner zone."""
        return [p for p in self.points
                if corner.brake_point_m - margin <= p.dist_m <= corner.exit_m + margin]

    # ─────────────────────────────────────────────

    def has_position_data(self) -> bool:
        if not self.points:
            return False
        samples = self.points[::max(1, len(self.points) // 10)]
        return any(abs(p.world_x) > 0.1 or abs(p.world_z) > 0.1 for p in samples)

    # ─────────────────────────────────────────────

    def build_spline(self):
        if not self.has_position_data():
            return

        valid = [
            (p.dist_m, p.world_x, p.world_z)
            for p in self.points
            if abs(p.world_x) > 0.1 or abs(p.world_z) > 0.1
        ]
        valid.sort(key=lambda t: t[0])
        if len(valid) < 20:
            return

        avg_spacing = (valid[-1][0] - valid[0][0]) / len(valid)
        win = max(1, int(5.0 / avg_spacing)) if avg_spacing > 0 else 3

        self._spline_dists.clear()
        self._spline_x.clear()
        self._spline_z.clear()

        for i in range(len(valid)):
            lo = max(0, i - win)
            hi = min(len(valid), i + win + 1)
            n = hi - lo
            self._spline_dists.append(valid[i][0])
            self._spline_x.append(sum(v[1] for v in valid[lo:hi]) / n)
            self._spline_z.append(sum(v[2] for v in valid[lo:hi]) / n)

    # ─────────────────────────────────────────────

    def get_line_at_dist(self, dist_m: float) -> Optional[tuple[float, float]]:
        if not self._spline_dists:
            return None
        dists = self._spline_dists
        if dist_m <= dists[0]:
            return (self._spline_x[0], self._spline_z[0])
        if dist_m >= dists[-1]:
            return (self._spline_x[-1], self._spline_z[-1])

        lo, hi = 0, len(dists) - 1
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if dists[mid] <= dist_m:
                lo = mid
            else:
                hi = mid

        if dists[hi] == dists[lo]:
            return (self._spline_x[lo], self._spline_z[lo])

        t = (dist_m - dists[lo]) / (dists[hi] - dists[lo])
        x = self._spline_x[lo] + t * (self._spline_x[hi] - self._spline_x[lo])
        z = self._spline_z[lo] + t * (self._spline_z[hi] - self._spline_z[lo])
        return (x, z)

    # ─────────────────────────────────────────────

    def get_lateral_deviation(self, dist_m: float, player_x: float,
                              player_z: float) -> Optional[float]:
        line_pos = self.get_line_at_dist(dist_m)
        if line_pos is None:
            return None
        ref_x, ref_z = line_pos
        ahead = self.get_line_at_dist(dist_m + 5)
        if ahead is None:
            return None
        dx = ahead[0] - ref_x
        dz = ahead[1] - ref_z
        track_len = math.sqrt(dx * dx + dz * dz)
        if track_len < 0.01:
            return None
        dx /= track_len
        dz /= track_len
        px = player_x - ref_x
        pz = player_z - ref_z
        lateral = px * dz - pz * dx
        return lateral


# ═══════════════════════════════════════════════════════════════════════════
# Reference Lap Loader
# ═══════════════════════════════════════════════════════════════════════════

class RefLapFile:
    """Metadata + telemetry from a reference lap CSV."""

    def __init__(self, path: str):
        self.path = path
        self.filename = os.path.basename(path)
        self.track_name = ""
        self.car_name = ""
        self.lap_time = 0.0
        self.track_length = 0.0
        self.event_type = ""
        self.date = ""
        self.car_class = ""
        self.trace: LapTrace = LapTrace()
        self.corners: list = []   # populated by corner_detection after loading
        self.is_valid: bool = True  # Default to valid, can be set to False for invalid laps
        self._parse()

    # ─────────────────────────────────────────────

    def _parse(self):
        with open(self.path, "r", encoding="utf-8-sig") as f:
            lines = f.readlines()

        telem_idx = None
        for i, line in enumerate(lines):
            low = line.lower()
            if "lapdistance" in low or "lap_distance" in low:
                telem_idx = i
                break

        if telem_idx is None:
            raise ValueError(f"No 'LapDistance' column found in {self.path}")

        # Metadata block
        try:
            mh = lines[1].strip().split(",")
            mv = lines[2].strip().split(",")
            meta = dict(zip(mh, mv))
            self.track_name = meta.get("track", "")
            self.car_name = meta.get("car", "")
            self.lap_time = float(meta.get("laptime [s]", 0))
            self.event_type = meta.get("event", "")
            self.date = meta.get("date", "")
            self.car_class = detect_car_class(self.car_name)
        except Exception:
            pass

        # Extended metadata
        try:
            eh = lines[3].strip().split(",")
            ev = lines[4].strip().split(",")
            ext = dict(zip(eh, ev))
            self.track_length = float(ext.get("Tracklen [m]", 0))
        except Exception:
            pass

        headers = lines[telem_idx].strip().split(",")
        col = {h.strip(): j for j, h in enumerate(headers)}
        col_lower = {h.lower(): h for h in col}

        def find_col(*candidates):
            for c in candidates:
                if c.lower() in col_lower:
                    return col[col_lower[c.lower()]]
            return None

        idx_dist     = find_col("LapDistance [m]", "lapdistance [m]")
        idx_speed    = find_col("Speed [km/h]", "Speed [m/s]", "speed [km/h]", "speed [m/s]")
        idx_throttle = find_col("ThrottlePercentage [%]", "throttle [%]")
        idx_brake    = find_col("BrakePercentage [%]", "brake [%]")
        idx_steer    = find_col("Steer [%]", "steer [%]")
        idx_gear     = find_col("Gear [int]", "gear [int]")
        idx_wx       = find_col("world_x [m]", "worldx [m]")
        idx_wy       = find_col("world_y [m]", "worldy [m]")
        idx_wz       = find_col("world_z [m]", "worldz [m]")

        if idx_dist is None or idx_speed is None:
            raise ValueError(f"Missing essential telemetry columns in {self.path}")

        speed_is_ms = False
        peek = []
        for line in lines[telem_idx + 1: telem_idx + 50]:
            parts = line.strip().split(",")
            if len(parts) > idx_speed:
                try:
                    peek.append(float(parts[idx_speed]))
                except:
                    pass
        if peek and max(peek) < 120:
            speed_is_ms = True

        speed_mult = 3.6 if speed_is_ms else 1.0
        points = []

        for line in lines[telem_idx + 1:]:
            parts = line.strip().split(",")
            if len(parts) <= idx_speed:
                continue
            try:
                wx = float(parts[idx_wx]) if idx_wx is not None and len(parts) > idx_wx else 0.0
                wy = float(parts[idx_wy]) if idx_wy is not None and len(parts) > idx_wy else 0.0
                wz = float(parts[idx_wz]) if idx_wz is not None and len(parts) > idx_wz else 0.0
                points.append(
                    TelPoint(
                        dist_m=float(parts[idx_dist]),
                        speed_kph=float(parts[idx_speed]) * speed_mult,
                        throttle_pct=float(parts[idx_throttle]) if idx_throttle is not None else 0,
                        brake_pct=float(parts[idx_brake]) if idx_brake is not None else 0,
                        steer_pct=float(parts[idx_steer]) if idx_steer is not None else 0,
                        gear=int(float(parts[idx_gear])) if idx_gear is not None else 0,
                        world_x=wx, world_y=wy, world_z=wz,
                    )
                )
            except:
                continue

        if not points:
            raise ValueError(f"No telemetry data parsed from {self.path}")

        self.trace = LapTrace(points=points, lap_time=self.lap_time)

        if self.trace.has_position_data():
            self.trace.build_spline()

        log.info(
            "Loaded: %s | %s @ %s | %.3fs | %d pts%s",
            self.filename[:40],
            self.car_name,
            self.track_name,
            self.lap_time,
            len(points),
            " [+XYZ]" if self.trace.has_position_data() else "",
        )

    # ─────────────────────────────────────────────

    def __str__(self):
        return f"{self.car_name} @ {self.track_name} — {self.lap_time:.3f}s ({self.event_type})"
