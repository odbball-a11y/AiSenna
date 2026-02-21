"""Fixed track map widget with proper scaling"""
import tkinter as tk
from tkinter import ttk
import numpy as np
import os
import pandas as pd
from typing import List, Tuple, Optional
import threading

class TrackMapWidgetFixed:
    def __init__(self, parent, width=300, height=200):
        self.parent = parent
        self.width = width
        self.height = height
        
        # Create canvas
        self.canvas = tk.Canvas(
            parent, width=width, height=height,
            bg="#0a0a1a", highlightthickness=0
        )
        
        # Track data
        self.lap_traces: List[List[Tuple[float, float]]] = []
        self.racing_line: List[Tuple[float, float]] = []
        self.current_pos: Optional[Tuple[float, float]] = None
        self.track_name: str = ""
        
        # Drawing state
        self.is_drawn = False
        
        # Draw placeholder
        self._draw_placeholder()
    
    def pack(self, **kwargs):
        """Pack the widget"""
        self.canvas.pack(**kwargs)
    
    def grid(self, **kwargs):
        """Grid the widget"""
        self.canvas.grid(**kwargs)
    
    def _draw_placeholder(self):
        """Draw placeholder before loading data"""
        self.canvas.delete("all")
        
        # Draw title
        self.canvas.create_text(
            self.width // 2, 20,
            text="TRACK MAP",
            fill="#e94560", font=("Arial", 12, "bold")
        )
        
        # Draw instructions
        self.canvas.create_text(
            self.width // 2, self.height // 2,
            text="Click 'Load Track' to begin",
            fill="#4fc3f7", font=("Arial", 10)
        )
    
    def load_track_data(self, track_name: str, laps_folder: str):
        """Load track data for the given track name"""
        self.track_name = track_name
        
        # Start loading in background thread
        thread = threading.Thread(
            target=self._load_track_data_thread,
            args=(track_name, laps_folder),
            daemon=True
        )
        thread.start()
    
    def _load_track_data_thread(self, track_name: str, laps_folder: str):
        """Load track data in background thread"""
        try:
            # Find track folder
            track_folder = None
            for root, dirs, files in os.walk(laps_folder):
                for dir_name in dirs:
                    if track_name.lower() in dir_name.lower():
                        track_folder = os.path.join(root, dir_name)
                        break
                if track_folder:
                    break
            
            if not track_folder:
                print(f"Track folder not found for: {track_name}")
                return
            
            # Find CSV files
            csv_files = [f for f in os.listdir(track_folder) 
                        if f.endswith('.csv') and 'live' in f]
            
            if not csv_files:
                print(f"No CSV files found in: {track_folder}")
                return
            
            # Load multiple laps
            self.lap_traces = []
            laps_loaded = 0
            
            for csv_file in csv_files[:5]:  # Load first 5 laps
                csv_path = os.path.join(track_folder, csv_file)
                points = self._load_lap_points(csv_path)
                if points and len(points) > 50:
                    self.lap_traces.append(points)
                    laps_loaded += 1
                    print(f"  Loaded lap {laps_loaded}: {len(points)} points")
                
                if laps_loaded >= 3:  # Load at least 3 good laps
                    break
            
            if not self.lap_traces:
                print(f"No points loaded from {track_name}")
                return
            
            print(f"Loaded {laps_loaded} laps for {track_name}")
            
            # Create racing line (use lap with most points)
            self._create_racing_line()
            
            # Update UI in main thread
            self.parent.after(0, self._draw_track_map)
            
        except Exception as e:
            print(f"Error loading track data: {e}")
            import traceback
            traceback.print_exc()
    
    def _load_lap_points(self, csv_path: str) -> List[Tuple[float, float]]:
        """Load points from a single CSV file"""
        try:
            # Find header line
            with open(csv_path, 'r') as f:
                lines = f.readlines()
            
            header_line = None
            for i, line in enumerate(lines):
                if 'lapdistance' in line.lower():
                    header_line = i
                    break
            
            if header_line is None:
                return []
            
            # Read data
            df = pd.read_csv(csv_path, skiprows=header_line)
            
            # Get coordinates
            x_col = 'world_x [m]'
            z_col = 'world_z [m]'
            
            if x_col not in df.columns or z_col not in df.columns:
                return []
            
            # Get all points (every 3rd for performance)
            xs = df[x_col].values[::3]
            zs = df[z_col].values[::3]
            
            # Remove NaN
            points = []
            for x, z in zip(xs, zs):
                if not np.isnan(x) and not np.isnan(z):
                    points.append((float(x), float(z)))
            
            return points
            
        except Exception as e:
            print(f"Error reading CSV {csv_path}: {e}")
            return []
    
    def _create_racing_line(self):
        """Create racing line from multiple laps"""
        if not self.lap_traces:
            return
        
        try:
            # Use the lap with most points as racing line
            self.racing_line = max(self.lap_traces, key=len)
            
            # Set current position
            if self.racing_line:
                self.current_pos = self.racing_line[0]
            
            print(f"Created racing line with {len(self.racing_line)} points")
            
        except Exception as e:
            print(f"Error creating racing line: {e}")
            # Use first lap as fallback
            if self.lap_traces:
                self.racing_line = self.lap_traces[0]
                if self.racing_line:
                    self.current_pos = self.racing_line[0]
    
    def _draw_track_map(self):
        """Draw the track map on canvas"""
        if not self.lap_traces:
            return
        
        self.canvas.delete("all")
        
        # Combine all points for bounds calculation
        all_points = []
        for lap in self.lap_traces:
            all_points.extend(lap)
        
        # Calculate bounds
        xs = [p[0] for p in all_points]
        zs = [p[1] for p in all_points]
        min_x, max_x = min(xs), max(xs)
        min_z, max_z = min(zs), max(zs)
        
        # Calculate track dimensions
        track_width = max_x - min_x
        track_height = max_z - min_z
        
        # Calculate canvas available space (with padding)
        canvas_width = self.width - 40  # 20px padding on each side
        canvas_height = self.height - 60  # 30px top, 30px bottom for labels
        
        # Calculate scale to fit track in canvas while maintaining aspect ratio
        scale_x = canvas_width / track_width if track_width > 0 else 1
        scale_z = canvas_height / track_height if track_height > 0 else 1
        scale = min(scale_x, scale_z) * 0.8  # Use 80% of available space
        
        # Calculate offset to center track
        center_x = (min_x + max_x) / 2
        center_z = (min_z + max_z) / 2
        
        # Function to convert track coordinates to canvas coordinates
        def track_to_canvas(x, z):
            # Scale and center
            x_canvas = (x - center_x) * scale + self.width / 2
            z_canvas = (z - center_z) * scale + self.height / 2
            
            # Flip Z axis (racing games often have inverted Z)
            z_canvas = self.height - z_canvas
            
            return x_canvas, z_canvas
        
        # Draw each lap trace
        for i, lap_points in enumerate(self.lap_traces):
            points = []
            for x, z in lap_points:
                x_canvas, z_canvas = track_to_canvas(x, z)
                points.extend([x_canvas, z_canvas])
            
            if points:
                # Different colors for different laps
                color = "#555555" if i > 0 else "#777777"
                self.canvas.create_line(
                    *points, fill=color, width=1, smooth=True
                )
        
        # Draw racing line
        if self.racing_line:
            points = []
            for x, z in self.racing_line:
                x_canvas, z_canvas = track_to_canvas(x, z)
                points.extend([x_canvas, z_canvas])
            
            if points:
                self.canvas.create_line(
                    *points, fill="#4fc3f7", width=2, smooth=True
                )
        
        # Draw current position
        if self.current_pos:
            x, z = self.current_pos
            x_canvas, z_canvas = track_to_canvas(x, z)
            
            self.canvas.create_oval(
                x_canvas - 4, z_canvas - 4,
                x_canvas + 4, z_canvas + 4,
                fill="#e94560", outline="white", width=1
            )
        
        # Draw title
        title = self.track_name[:25] + "..." if len(self.track_name) > 25 else self.track_name
        self.canvas.create_text(
            self.width // 2, 20,
            text=title.upper(),
            fill="#e94560", font=("Arial", 11, "bold")
        )
        
        # Draw info
        info = f"{len(self.lap_traces)} laps • Scale: {scale:.3f}"
        self.canvas.create_text(
            self.width // 2, self.height - 40,
            text=info,
            fill="#4fc3f7", font=("Arial", 9)
        )
        
        # Draw bounds info
        bounds = f"X:{min_x:.0f}→{max_x:.0f} Z:{min_z:.0f}→{max_z:.0f}"
        self.canvas.create_text(
            self.width // 2, self.height - 25,
            text=bounds,
            fill="#888888", font=("Arial", 8)
        )
        
        # Draw legend
        self.canvas.create_text(10, self.height - 10, text="Grey: Lap Traces", 
                               fill="#777777", anchor="w", font=("Arial", 8))
        self.canvas.create_text(self.width - 10, self.height - 10, text="Blue: Racing Line", 
                               fill="#4fc3f7", anchor="e", font=("Arial", 8))
        
        self.is_drawn = True
        print(f"Track map drawn. Scale: {scale:.3f}, Bounds: X({min_x:.0f},{max_x:.0f}) Z({min_z:.0f},{max_z:.0f})")
    
    def update_position(self, x: float, z: float):
        """Update car position on track"""
        if not self.is_drawn:
            return
        
        self.current_pos = (x, z)
        
        # Redraw
        self._draw_track_map()
    
    def clear(self):
        """Clear track map"""
        self.lap_traces = []
        self.racing_line = []
        self.current_pos = None
        self.track_name = ""
        self.is_drawn = False
        self._draw_placeholder()

# Test the widget
if __name__ == "__main__":
    root = tk.Tk()
    root.title("Track Map Test")
    root.geometry("500x400")
    
    track_map = TrackMapWidgetFixed(root, width=450, height=350)
    track_map.pack(pady=10)
    
    # Test button
    def load_silverstone():
        track_map.load_track_data("Silverstone", "senna_ai/opponent_laps")
    
    btn = tk.Button(root, text="Load Silverstone", command=load_silverstone)
    btn.pack(pady=10)
    
    root.mainloop()
