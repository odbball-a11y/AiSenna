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
