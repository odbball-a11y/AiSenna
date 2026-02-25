# -*- coding: utf-8 -*-
from pathlib import Path
import logging
from typing import List, Tuple

from senna_ai.telemetry.models import RefLapFile


log = logging.getLogger(__name__)


def scan_lap_files(folder: str) -> Tuple[List[RefLapFile], List[str]]:
    """
    Recursively scan a folder (and all subfolders) for reference lap CSVs.
    """
    laps: List[RefLapFile] = []
    errors: List[str] = []

    folder_path = Path(folder)

    if not folder_path.exists():
        return [], [f"Folder not found: {folder}"]

    # 🔥 RECURSIVE search
    csv_files = sorted(folder_path.rglob("*.csv"))

    log.info("Scanning %s — found %d CSV files", folder, len(csv_files))

    if not csv_files:
        return [], [f"No .csv files found in {folder} or subfolders"]

    for f in csv_files:
        try:
            log.info("Loading lap: %s", f)
            lap = RefLapFile(str(f))

            # Only accept valid laps
            if lap.track_name and lap.trace and lap.trace.points:
                laps.append(lap)
                log.info("Loaded OK: %s", f.name)
            else:
                log.warning("Invalid lap data: %s", f.name)

        except Exception as e:
            log.error("Failed loading %s: %s", f.name, e)
            errors.append(f"{f.name}: {e}")

    return laps, errors


def filter_laps_by_cluster(laps: List[RefLapFile],
                            gap_threshold: float = 5.0) -> List[RefLapFile]:
    """
    Remove isolated fast-cluster outliers (e.g. flying laps, cheat laps).

    Sort by lap_time. Walk from fastest outward. The first gap > gap_threshold
    between adjacent laps signals a performance discontinuity — treat everything
    BELOW that gap as a separate cluster and discard it.

    Example: laps sorted [83.4, 83.6, 102.1, 102.4 ...] → gap at index 1→2 is 18.5s
             → discard laps 83.4 and 83.6, return from 102.1 onward.

    If no gap is found, all laps are returned unchanged.
    """
    if len(laps) < 2:
        return laps

    sorted_laps = sorted(laps, key=lambda l: l.lap_time)
    times = [l.lap_time for l in sorted_laps]

    for i in range(len(times) - 1):
        if times[i + 1] - times[i] > gap_threshold:
            discarded = i + 1
            log.info(
                "filter_laps_by_cluster: gap %.1fs at index %d→%d "
                "(%.3fs→%.3fs) — discarding %d outlier lap(s)",
                times[i + 1] - times[i], i, i + 1,
                times[i], times[i + 1], discarded,
            )
            return sorted_laps[discarded:]

    return sorted_laps
