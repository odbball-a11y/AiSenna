import os
import tkinter as tk
from tkinter import ttk, filedialog
import logging
import logging

from senna_ai.infra.tts_engine import Speaker, TTS_RATE
from senna_ai.coaching.engine import CoachingEngine
from senna_ai.infra.lmu_reader import LMUReader
from senna_ai.data.lap_scanner import scan_lap_files
from senna_ai.telemetry.models import RefLapFile
from senna_ai.track.composite_builder import CompositeLap
from senna_ai.coaching.coaching_constants import TIER_PROMOTION_LAPS
log = logging.getLogger(__name__)


import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


import argparse
import os

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--laps-folder",
        default=os.path.join(
            os.path.dirname(__file__),
            "opponent_laps"
        )
    )
    args = parser.parse_args()

    app = SennaCoachApp(laps_folder=args.laps_folder)
    app.run()

if __name__ == "__main__":
    main()


# ═══════════════════════════════════════════════════════════════════════════
# Tkinter UI
# ═══════════════════════════════════════════════════════════════════════════
class SennaCoachApp:
    def __init__(self, laps_folder: str | None = None):
        if laps_folder in (None, ...):
            raise ValueError(
                "laps_folder must be provided.\n"
                "Run with: python -m senna_ai.main --laps-folder <path>"
            )

        self.laps_folder = laps_folder
        self.all_laps: list[RefLapFile] = []
        self.filtered_laps: list[RefLapFile] = []
        # Core components
        self.speaker = Speaker(rate=TTS_RATE)
        self.engine = CoachingEngine(self.speaker, on_state_change=self._on_state_change)
        self.reader = LMUReader(
            self.engine,
            on_telemetry=self._on_telemetry,
            save_folder=os.path.join(self.laps_folder, "live_captures"),
            on_new_opponent_lap=self._on_new_opponent_lap,
        )

        # Build UI
        self.root = tk.Tk()
        self.root.title("Senna Coach v2 — Adaptive Voice Driving Coach")
        self.root.geometry("740x920")
        self.root.configure(bg="#1a1a2e")
        self.root.resizable(False, False)

        self._build_ui()
        self._scan_laps()
        self.reader.start()
        self._update_ui_tick()

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"),
                        foreground="#e94560", background="#1a1a2e")
        style.configure("Info.TLabel", font=("Segoe UI", 11),
                        foreground="#c4c4c4", background="#1a1a2e")
        style.configure("Phase.TLabel", font=("Segoe UI", 14, "bold"),
                        foreground="#0f3460", background="#e94560",
                        padding=(12, 6))
        style.configure("Corner.TLabel", font=("Segoe UI", 13, "bold"),
                        foreground="#53d769", background="#1a1a2e")
        style.configure("Big.TButton", font=("Segoe UI", 12, "bold"), padding=10)
        style.configure("Dark.TFrame", background="#1a1a2e")
        style.configure("Card.TFrame", background="#16213e")
        style.configure("Bar.TFrame", background="#0f3460")
        style.configure("CardLabel.TLabel", font=("Segoe UI", 10),
                        foreground="#c4c4c4", background="#16213e")
        style.configure("CardValue.TLabel", font=("Consolas", 22, "bold"),
                        foreground="#e94560", background="#16213e")

        main = ttk.Frame(self.root, style="Dark.TFrame")
        main.pack(fill="both", expand=True, padx=16, pady=12)

        # Title
        ttk.Label(main, text="🏎️  SENNA COACH v2", style="Title.TLabel").pack(anchor="w")
        ttk.Label(main, text="Adaptive corner-by-corner coaching — improves with you",
                  style="Info.TLabel").pack(anchor="w", pady=(0, 12))

        # Track filter
        filter_frame = ttk.Frame(main, style="Dark.TFrame")
        filter_frame.pack(fill="x", pady=(0, 6))
        ttk.Label(filter_frame, text="Track:", style="Info.TLabel").pack(side="left")
        self.track_filter_var = tk.StringVar(value="(all)")
        self.track_combo = ttk.Combobox(
            filter_frame, textvariable=self.track_filter_var, width=30, state="readonly",
        )
        self.track_combo.pack(side="left", padx=8)
        self.track_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_filter())

        ttk.Label(filter_frame, text="Class:", style="Info.TLabel").pack(side="left")
        self.class_filter_var = tk.StringVar(value="(auto)")
        self.class_combo = ttk.Combobox(
            filter_frame, textvariable=self.class_filter_var, width=12, state="readonly",
        )
        self.class_combo.pack(side="left", padx=8)
        self.class_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_filter())

        # Lap list
        self.lap_listbox = tk.Listbox(
            main, height=6, font=("Consolas", 10), selectmode="extended",
            bg="#16213e", fg="#c4c4c4", selectbackground="#e94560",
        )
        self.lap_listbox.pack(fill="x", pady=(0, 6))

        # Info label
        self.info_label = ttk.Label(main, text="Select laps above, then press START",
                                    style="Info.TLabel")
        self.info_label.pack(anchor="w", pady=(0, 8))

        # Buttons row
        btn_frame = ttk.Frame(main, style="Dark.TFrame")
        btn_frame.pack(fill="x", pady=(0, 10))

        self.start_btn = ttk.Button(btn_frame, text="▶ START", style="Big.TButton",
                                    command=self._on_start)
        self.start_btn.pack(side="left")

        self.stop_btn = ttk.Button(btn_frame, text="■ STOP", style="Big.TButton",
                                   command=self._on_stop)
        self.stop_btn.pack(side="left", padx=8)

        ttk.Label(btn_frame, text="Vol:", style="Info.TLabel").pack(side="left", padx=(16, 4))
        self.volume_var = tk.IntVar(value=150)
        self.volume_slider = tk.Scale(
            btn_frame, from_=50, to=200, orient="horizontal",
            variable=self.volume_var, command=self._on_volume_change,
            length=120, bg="#1a1a2e", fg="#c4c4c4", troughcolor="#0f3460",
            highlightthickness=0, sliderrelief="flat",
        )
        self.volume_slider.pack(side="left")

        # Phase label
        self.phase_label = ttk.Label(main, text="WAITING", style="Phase.TLabel")
        self.phase_label.pack(fill="x", pady=(0, 8))

        # Corner instruction
        self.corner_label = ttk.Label(main, text="", style="Corner.TLabel")
        self.corner_label.pack(fill="x", pady=(0, 8))

        # Telemetry cards
        card_frame = ttk.Frame(main, style="Dark.TFrame")
        card_frame.pack(fill="x")

        self._cards = {}
        for label, key, width in [("SPEED", "speed", 90), ("THRTL", "throttle", 80),
                                   ("BRAKE", "brake", 80), ("GEAR", "gear", 60),
                                   ("LAP", "lap", 60)]:
            card = ttk.Frame(card_frame, style="Card.TFrame", width=width, height=70)
            card.pack(side="left", expand=True, fill="both", padx=2, pady=3)
            card.pack_propagate(False)
            ttk.Label(card, text=label, style="CardLabel.TLabel").pack(anchor="center", pady=(6, 0))
            val_lbl = ttk.Label(card, text="—", style="CardValue.TLabel")
            val_lbl.pack(anchor="center", expand=True)
            self._cards[key] = val_lbl

        # Timing cards — smaller font for lap times
        style.configure("TimeValue.TLabel", font=("Consolas", 16, "bold"),
                        foreground="#e94560", background="#16213e")
        style.configure("PBValue.TLabel", font=("Consolas", 16, "bold"),
                        foreground="#FFD700", background="#16213e")
        style.configure("TargetValue.TLabel", font=("Consolas", 16, "bold"),
                        foreground="#53d769", background="#16213e")

        for label, key, lbl_style, width in [
            ("LAST", "last", "TimeValue.TLabel", 100),
            ("PB", "pb", "PBValue.TLabel", 100),
            ("TARGET", "target", "TargetValue.TLabel", 100),
        ]:
            card = ttk.Frame(card_frame, style="Card.TFrame", width=width, height=70)
            card.pack(side="left", expand=True, fill="both", padx=2, pady=3)
            card.pack_propagate(False)
            ttk.Label(card, text=label, style="CardLabel.TLabel").pack(anchor="center", pady=(6, 0))
            val_lbl = ttk.Label(card, text="—", style=lbl_style)
            val_lbl.pack(anchor="center", expand=True)
            self._cards[key] = val_lbl

        # ── Sector analysis table ──
        sector_header = ttk.Frame(main, style="Dark.TFrame")

        # Track Map Overlay (minimal 2D validation)
        track_map_header = ttk.Frame(main, style="Dark.TFrame")
        track_map_header.pack(fill="x", pady=(8, 2))
        ttk.Label(track_map_header, text="TRACK MAP",
                  font=("Segoe UI", 10, "bold"),
                  foreground="#e94560", background="#1a1a2e").pack(side="left")
        
        # Track map canvas
        self.track_map_canvas = tk.Canvas(
            main, width=400, height=400,
            bg="#0a0a1a", highlightthickness=0
        )
        self.track_map_canvas.pack(pady=(0, 8))
        
        # Track map state
        self.track_map_bounds = None
        self.track_map_initialized = False

        sector_header.pack(fill="x", pady=(8, 2))
        ttk.Label(sector_header, text="SECTOR ANALYSIS",
                  font=("Segoe UI", 10, "bold"),
                  foreground="#e94560", background="#1a1a2e").pack(side="left")
        self.tier_label = ttk.Label(sector_header, text="", style="Info.TLabel")
        self.tier_label.pack(side="right")

        # Column headers
        hdr_frame = ttk.Frame(main, style="Bar.TFrame")
        hdr_frame.pack(fill="x")
        hdr_font = ("Consolas", 8, "bold")
        hdr_fg = "#c4c4c4"
        hdr_bg = "#0f3460"
        for text, w in [("SEC", 4), ("LAST", 7), ("PB", 7), ("TGT", 7),
                        ("Δ TGT", 6), ("BRK", 3), ("PRS", 3), ("TRN", 3),
                        ("APX", 3), ("EXIT", 3), ("LINE", 3), ("STG", 4)]:
            ttk.Label(hdr_frame, text=text, width=w, anchor="center",
                      font=hdr_font, foreground=hdr_fg, background=hdr_bg,
                      ).pack(side="left", padx=1)

        # Sector rows (will be populated dynamically)
        self._sector_row_frame = ttk.Frame(main, style="Dark.TFrame")
        self._sector_row_frame.pack(fill="x")
        self._sector_row_labels: list[list[tk.Label]] = []

        # ── Live capture feed (compact) ──
        capture_header = ttk.Frame(main, style="Dark.TFrame")
        capture_header.pack(fill="x", pady=(6, 1))
        ttk.Label(capture_header, text="LIVE CAPTURES",
                  font=("Segoe UI", 9, "bold"),
                  foreground="#e94560", background="#1a1a2e").pack(side="left")
        self.capture_count_label = ttk.Label(
            capture_header, text="", style="Info.TLabel",
        )
        self.capture_count_label.pack(side="right")

        self.capture_listbox = tk.Listbox(
            main, height=3, font=("Consolas", 8),
            bg="#16213e", fg="#53d769", selectbackground="#0f3460",
        )
        self.capture_listbox.pack(fill="x", pady=(0, 2))

    def _scan_laps(self):
        self.all_laps = []
        folders = [self.laps_folder]

        # Also scan opponent_laps subfolder if it exists
        opp_folder = os.path.join(self.laps_folder, "opponent_laps", "lmu")
        if os.path.isdir(opp_folder):
            folders.append(opp_folder)

        # Also scan live captures from previous sessions
        live_folder = os.path.join(self.laps_folder, "live_captures")
        if os.path.isdir(live_folder) and live_folder not in folders:
            folders.append(live_folder)

        for folder in folders:
            laps, errors = scan_lap_files(folder)
            log.info("Found %d lap(s) in %s", len(laps), folder)
            self.all_laps.extend(laps)

        # Populate track filter
        tracks = sorted(set(l.track_name for l in self.all_laps if l.track_name))
        self.track_combo["values"] = ["(all)"] + tracks

        # Populate class filter
        classes = sorted(set(l.car_class for l in self.all_laps if l.car_class and l.car_class != "Unknown"))
        self.class_combo["values"] = ["(auto)", "(all)"] + classes

        self._apply_filter()

    def _apply_filter(self):
        track = self.track_filter_var.get()
        cls = self.class_filter_var.get()

        filtered = self.all_laps[:]

        if track != "(all)":
            filtered = [l for l in filtered if l.track_name == track]

        if cls == "(auto)":
            # Will be resolved at start time based on player car
            pass
        elif cls != "(all)":
            filtered = [l for l in filtered if l.car_class == cls]

        self.filtered_laps = filtered
        self.filtered_laps.sort(key=lambda l: l.lap_time if l.lap_time > 0 else 9999)

        self.lap_listbox.delete(0, tk.END)
        for lap in self.filtered_laps:
            cls_tag = f"[{lap.car_class}]" if lap.car_class != "Unknown" else ""
            label = f"{lap.lap_time:7.3f}s | {cls_tag:12s} {lap.car_name[:22]:22s} | {lap.track_name[:25]}"
            self.lap_listbox.insert(tk.END, label)

        log.info("Lap list: %d shown (filtered from %d total)",
                 len(self.filtered_laps), len(self.all_laps))

    def _on_start(self):
        """
        Fully automatic start — zero clicks needed.

        Priority order for building composite:
          1. Same track + same car class (best: like-for-like comparison)
          2. Same track + any class (fallback: corners still valid, speeds differ)
          3. No laps at all → voice says "no reference data", starts capturing

        Within each group, all laps are used for the composite (more = better tiers).
        """
        track = self.reader.current_track or ""
        car = self.reader.current_car or ""
        car_class = self.engine.current_car_class or ""

        log.info("Auto-start: track='%s', car='%s', class='%s'", track, car, car_class)

        # If we don't know the track yet, try using the track filter
        if not track:
            track = self.track_filter_var.get()
            if track == "(all)":
                track = ""

        # ── Step 1: Find laps for this track ──
        track_laps = [l for l in self.all_laps
                      if l.track_name and track
                      and l.track_name.lower() == track.lower()]

        if not track_laps and track:
            # Fuzzy match — track names might differ slightly
            track_laps = [l for l in self.all_laps
                          if l.track_name and track
                          and (track.lower() in l.track_name.lower()
                               or l.track_name.lower() in track.lower())]

        # ── Step 2: Filter by car class ──
        class_laps = []
        other_laps = []

        if car_class and car_class != "Unknown":
            for lap in track_laps:
                if lap.car_class == car_class:
                    class_laps.append(lap)
                else:
                    other_laps.append(lap)
        else:
            # No class detected — use all track laps
            class_laps = track_laps

        # ── Step 3: Choose the best set ──
        chosen_laps = []
        status_msg = ""

        if class_laps:
            chosen_laps = class_laps
            status_msg = (
                f"{len(chosen_laps)} {car_class} laps on {track[:25]}. "
                f"Building composite."
            )
            self.speaker.say(
                f"Found {len(chosen_laps)} {car_class} reference laps. "
                f"Building composite. Drive when ready."
            )
        elif other_laps:
            # Different class but same track — still useful for corner locations
            chosen_laps = other_laps
            classes_found = set(l.car_class for l in other_laps if l.car_class != "Unknown")
            cls_str = ", ".join(classes_found) if classes_found else "mixed"
            status_msg = (
                f"No {car_class} laps. Using {len(other_laps)} {cls_str} laps. "
                f"Speeds will differ but corners are valid."
            )
            self.speaker.say(
                f"No {car_class} laps found. Using {len(other_laps)} "
                f"{cls_str} laps as reference. Corner positions are valid "
                f"but target speeds will be approximate."
            )
        elif track:
            status_msg = f"No reference laps for {track[:25]}. Recording opponents."
            self.speaker.say(
                f"No reference laps yet for this track. "
                f"I'll start recording opponent laps. "
                f"Drive a few laps and I'll build your targets."
            )
        else:
            status_msg = "Waiting for track detection. Drive onto the track."
            self.speaker.say(
                "Cannot detect the track yet. Drive onto the track and press start again."
            )
            return

        # ── Step 4: Start coaching ──
        if chosen_laps:
            self.engine.set_reference_laps(chosen_laps)
            self.engine.start()
            status_msg += f" {len(self.engine.corners)} corners."
        else:
            # No laps — start in learning mode (will capture opponents)
            self.engine.phase = self.engine.PHASE_COACHING
            self.engine.corners = []  # Will be built once first opponent lap arrives
            # Store track/class so hot-reload bootstrap can match incoming laps
            self.engine.current_track = track
            self.engine.current_car_class = car_class

        self.info_label.config(text=status_msg)
        log.info("Auto-start result: %s", status_msg)

    def _on_stop(self):
        self.engine.stop()
        self.info_label.config(text="Coach stopped.")

    def _on_volume_change(self, val):
        self.speaker.volume = int(float(val))

    def _on_state_change(self):
        pass  # UI update happens in tick

    def _on_telemetry(self, dist, speed, throttle, brake, gear):
        pass

    def _on_new_opponent_lap(self, csv_path: str):
        """Called when opponent tracker saves a new fast lap. Hot-reload it."""
        try:
            new_lap = RefLapFile(csv_path)
            if new_lap.track_name and new_lap.trace.points:
                self.all_laps.append(new_lap)

                # Add to capture feed in UI (thread-safe via root.after)
                cls_tag = f"[{new_lap.car_class}]" if new_lap.car_class != "Unknown" else ""
                entry = (f"💾 {new_lap.lap_time:7.3f}s  {cls_tag:12s} "
                         f"{new_lap.car_name[:28]}  ({len(new_lap.trace.points)} pts)")
                try:
                    self.root.after(0, self._add_capture_entry, entry)
                except Exception:
                    pass

                log.info("🔄 Hot-loaded: %s (%.3fs)", new_lap.filename, new_lap.lap_time)

                # ── Bootstrap: if coaching is waiting for laps, try to start ──
                if (self.engine.phase == self.engine.PHASE_COACHING
                        and not self.engine.corners):
                    # We started with no laps. Check if we now have enough
                    # class-matched laps to bootstrap coaching.
                    player_class = self.engine.current_car_class or ""
                    track = self.engine.current_track or ""
                    log.info("🔍 Bootstrap check: player_class='%s', track='%s', "
                             "all_laps=%d", player_class, track, len(self.all_laps))

                    matched = [l for l in self.all_laps
                               if l.track_name and track
                               and l.track_name.lower()[:20] == track.lower()[:20]
                               and (l.car_class == player_class
                                    or player_class == "Unknown"
                                    or l.car_class == "Unknown")]

                    log.info("🔍 Bootstrap: %d track-matched, %d class-matched out of %d total",
                             sum(1 for l in self.all_laps
                                 if l.track_name and track
                                 and l.track_name.lower()[:20] == track.lower()[:20]),
                             len(matched), len(self.all_laps))

                    MIN_BOOTSTRAP = 3
                    if len(matched) >= MIN_BOOTSTRAP:
                        log.info("🚀 Bootstrap: %d class-matched laps available. "
                                 "Building initial composite.", len(matched))
                        self.engine.set_reference_laps(matched)
                        if self.engine.corners:
                            self.engine.start()
                            self.speaker.say(
                                f"I have {len(matched)} reference laps now. "
                                f"Coaching is active. {len(self.engine.corners)} corners detected."
                            )
                        else:
                            log.warning("🚀 Bootstrap: set_reference_laps found no corners! "
                                        "Waiting for more laps.")
                        try:
                            self.root.after(0, lambda: self.info_label.config(
                                text=f"Coaching: {len(self.engine.corners)} corners, "
                                     f"{len(matched)} refs"))
                        except Exception:
                            pass

                # ── Rebuild: if coaching already active, add new lap and rebuild ──
                elif (self.engine.phase == self.engine.PHASE_COACHING
                        and self.engine.ref_laps):
                    # Check this lap matches current track/class
                    player_class = self.engine.current_car_class or ""
                    track = self.engine.current_track or ""
                    if (new_lap.track_name
                            and track
                            and new_lap.track_name.lower()[:20] == track.lower()[:20]
                            and (new_lap.car_class == player_class
                                 or player_class == "Unknown"
                                 or new_lap.car_class == "Unknown")):
                        self.engine.ref_laps.append(new_lap)
                        self._rebuild_composite()
        except Exception as e:
            log.warning("Failed to hot-load opponent lap: %s", e)

    def _add_capture_entry(self, text: str):
        """Add an entry to the capture listbox (must be called from main thread)."""
        self.capture_listbox.insert(0, text)  # Newest at top
        # Keep list manageable
        while self.capture_listbox.size() > 50:
            self.capture_listbox.delete(50)

    def _rebuild_composite(self):
        """Rebuild composite from current ref_laps, preserving tier progress."""
        if not self.engine.corners or not self.engine.ref_laps:
            return

        old_composite = self.engine.composite
        new_composite = CompositeLap(self.engine.corners, self.engine.ref_laps)

        # Preserve tier progress from old composite
        if old_composite:
            for idx, old_ct in old_composite.targets.items():
                new_ct = new_composite.targets.get(idx)
                if new_ct:
                    new_ct.tier = min(old_ct.tier, len(new_ct.available_traces) - 1)
                    new_ct.consecutive_beats = old_ct.consecutive_beats
                    new_ct.player_best_apex_speed = old_ct.player_best_apex_speed
                    new_composite._apply_tier(new_ct)

        self.engine.composite = new_composite
        log.info("🔄 Composite rebuilt with %d reference laps", len(self.engine.ref_laps))

    def _update_ui_tick(self):
        eng = self.engine

        phase_text = eng.phase.upper()
        if eng.phase == eng.PHASE_COACHING:
            ready = len(eng._corner_ready)
            total = len(eng.corners)
            if ready < total:
                phase_text = f"LEARNING ({ready}/{total})"
            else:
                phase_text = f"COACHING — LAP {eng.lap_count}"

        self.phase_label.config(text=phase_text)
        self.corner_label.config(text=eng.current_corner_label)

        self._cards["speed"].config(text=f"{eng.live_speed:.0f}")
        self._cards["throttle"].config(text=f"{eng.live_throttle:.0f}%")
        self._cards["brake"].config(text=f"{eng.live_brake:.0f}%")
        self._cards["gear"].config(text=f"{eng.live_gear}")
        self._cards["lap"].config(text=f"{eng.lap_count}")

        # Lap times
        def fmt_time(t):
            if t <= 0:
                return "—"
            mins = int(t) // 60
            secs = t - mins * 60
            return f"{mins}:{secs:05.2f}" if mins else f"{secs:.2f}"

        self._cards["last"].config(text=fmt_time(eng.last_lap_time))
        self._cards["pb"].config(text=fmt_time(eng.best_lap_time))

        # Composite target time
        if eng.composite:
            comp_time = eng.composite.get_composite_time_estimate()
            self._cards["target"].config(text=fmt_time(comp_time))
        else:
            self._cards["target"].config(text="—")

        # ── Track Map Drawing ──
        if self.track_map_canvas and eng.reference_line:
            # Initialize bounds if needed
            if not self.track_map_initialized and eng.reference_line:
                # Calculate bounds from reference line
                xs = [p[0] for p in eng.reference_line]
                ys = [p[1] for p in eng.reference_line]
                if xs and ys:
                    min_x, max_x = min(xs), max(xs)
                    min_y, max_y = min(ys), max(ys)
                    # Add 10% margin
                    margin_x = (max_x - min_x) * 0.1
                    margin_y = (max_y - min_y) * 0.1
                    self.track_map_bounds = (
                        min_x - margin_x, max_x + margin_x,
                        min_y - margin_y, max_y + margin_y
                    )
                    self.track_map_initialized = True
                    print(f"Track map bounds: {self.track_map_bounds}")
            
            # Clear canvas
            self.track_map_canvas.delete("all")
            
            # Draw reference line (grey)
            if eng.reference_line and self.track_map_bounds:
                min_x, max_x, min_y, max_y = self.track_map_bounds
                points = []
                for x, y in eng.reference_line:
                    x_norm = (x - min_x) / (max_x - min_x)
                    y_norm = (y - min_y) / (max_y - min_y)
                    x_canvas = 10 + x_norm * 380
                    y_canvas = 10 + (1 - y_norm) * 380  # Flip Y so forward is up
                    points.extend([x_canvas, y_canvas])
                if len(points) >= 4:
                    self.track_map_canvas.create_line(
                        *points, fill="#666666", width=2, smooth=True
                    )
            
            # Draw player trace (blue)
            if hasattr(eng, "_all_points") and eng._all_points and self.track_map_bounds:
                min_x, max_x, min_y, max_y = self.track_map_bounds
                points = []
                # Take last 100 points
                for x, y in list(eng._all_points)[-100:]:
                    x_norm = (x - min_x) / (max_x - min_x)
                    y_norm = (y - min_y) / (max_y - min_y)
                    x_canvas = 10 + x_norm * 380
                    y_canvas = 10 + (1 - y_norm) * 380
                    points.extend([x_canvas, y_canvas])
                if len(points) >= 4:
                    self.track_map_canvas.create_line(
                        *points, fill="#4fc3f7", width=1.5, smooth=True
                    )
            
            # Draw current position (red dot)
            if eng.live_x is not None and eng.live_z is not None and self.track_map_bounds:
                min_x, max_x, min_y, max_y = self.track_map_bounds
                x_norm = (eng.live_x - min_x) / (max_x - min_x)
                y_norm = (eng.live_z - min_y) / (max_y - min_y)
                x_canvas = 10 + x_norm * 380
                y_canvas = 10 + (1 - y_norm) * 380
                self.track_map_canvas.create_oval(
                    x_canvas - 4, y_canvas - 4,
                    x_canvas + 4, y_canvas + 4,
                    fill="#e94560", outline="white", width=1
                )


        # ── Sector table ──
        # Use last_sector_results (completed lap) merged with current sector_results
        display_results = eng.last_sector_results if eng.last_sector_results else eng.sector_results
        num_sectors = len(eng.sectors)

        # Build rows if sectors changed
        if num_sectors > 0 and len(self._sector_row_labels) != num_sectors:
            # Clear old rows
            for widget in self._sector_row_frame.winfo_children():
                widget.destroy()
            self._sector_row_labels = []

            row_font = ("Consolas", 9)
            grade_colours = {"good": "#53d769", "ok": "#FFD700", "poor": "#e94560", "": "#555555"}

            for s in eng.sectors:
                row = ttk.Frame(self._sector_row_frame, style="Dark.TFrame")
                row.pack(fill="x", pady=1)
                labels = []
                for w in [4, 7, 7, 7, 6, 3, 3, 3, 3, 3, 3, 4]:
                    lbl = tk.Label(row, text="—", width=w, anchor="center",
                                   font=row_font, fg="#c4c4c4", bg="#16213e")
                    lbl.pack(side="left", padx=1)
                    labels.append(lbl)
                # Set sector number
                labels[0].config(text=f"S{s.index}")
                self._sector_row_labels.append(labels)

        # Populate sector rows
        grade_colours = {"good": "#53d769", "ok": "#FFD700", "poor": "#e94560", "": "#555555"}

        for i, s in enumerate(eng.sectors):
            if i >= len(self._sector_row_labels):
                break
            labels = self._sector_row_labels[i]

            # Find result for this sector
            result = None
            for r in display_results:
                if r.sector_idx == s.index:
                    result = r
                    break

            # Also check current in-progress results
            if result is None:
                for r in eng.sector_results:
                    if r.sector_idx == s.index:
                        result = r
                        break

            pb = eng.sector_pb.get(s.index, 0)
            tgt = eng.sector_target.get(s.index, 0)

            def fmt_s(t):
                return f"{t:.2f}" if t > 0 else "—"

            if result:
                labels[1].config(text=fmt_s(result.time))       # LAST
                labels[2].config(text=fmt_s(pb))                 # PB
                labels[3].config(text=fmt_s(tgt))                # TGT
                # Delta to target
                if result.delta_to_target != 0 and tgt > 0:
                    d = result.delta_to_target
                    sign = "+" if d > 0 else ""
                    colour = "#53d769" if d < -0.1 else ("#e94560" if d > 0.1 else "#c4c4c4")
                    labels[4].config(text=f"{sign}{d:.2f}", fg=colour)
                else:
                    labels[4].config(text="—", fg="#555555")
                # Grades
                for j, grade in enumerate([result.brake_grade, result.pressure_grade,
                                            result.turn_in_grade, result.apex_grade,
                                            result.exit_grade, result.line_grade]):
                    symbol = "●" if grade == "good" else ("◐" if grade == "ok" else ("○" if grade == "poor" else "—"))
                    labels[5 + j].config(text=symbol, fg=grade_colours.get(grade, "#555555"))

                # Force stage (STG column = index 11)
                fs = eng.force_model.scores.get(s.index)
                if fs and len(labels) > 11:
                    stage_colours = {1: "#e94560", 2: "#FFD700", 3: "#4fc3f7", 4: "#53d769"}
                    labels[11].config(
                        text=f"S{fs.current_stage}",
                        fg=stage_colours.get(fs.current_stage, "#c4c4c4"),
                    )
                elif len(labels) > 11:
                    labels[11].config(text="—", fg="#555555")

                # Highlight current sector
                is_current = (eng._current_sector_idx == s.index)
                bg = "#1e2d4d" if is_current else "#16213e"
                for lbl in labels:
                    lbl.config(bg=bg)
            else:
                labels[1].config(text="—")
                labels[2].config(text=fmt_s(pb))
                labels[3].config(text=fmt_s(tgt))
                labels[4].config(text="—", fg="#555555")
                for j in range(7):  # 6 grades + 1 stage
                    labels[5 + j].config(text="—", fg="#555555")

        # Tier summary on sector header
        if eng.composite and eng.corners:
            tier_parts = []
            for c in eng.corners:
                ct = eng.composite.targets.get(c.index)
                if ct:
                    beats = "●" * ct.consecutive_beats + "○" * (TIER_PROMOTION_LAPS - ct.consecutive_beats)
                    tier_parts.append(f"T{ct.tier+1}[{beats}]")
            self.tier_label.config(text="  ".join(tier_parts))

        # Opponent tracker status
        if self.reader.opp_tracker:
            ot = self.reader.opp_tracker
            synced = sum(1 for o in ot._opponents.values() if o.synced)
            total_opp = ot.opponent_count
            self.capture_count_label.config(
                text=f"👁️ {total_opp} opponents ({synced} synced)  |  "
                     f"💾 {ot.saved_count} saved  |  "
                     f"Track: {ot._track_length:.0f}m"
            )

        self.root.after(50, self._update_ui_tick)

    def run(self):
        self.root.mainloop()
        self.reader.stop()
        self.speaker.stop()
