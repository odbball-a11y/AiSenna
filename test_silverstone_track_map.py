"""Test Silverstone track map with real data"""
import tkinter as tk
from tkinter import ttk
import pandas as pd
import numpy as np
import os

class SilverstoneTrackMap:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Silverstone Track Map")
        self.root.geometry("800x600")
        self.root.configure(bg="#1a1a2e")
        
        # Create main frame
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Create canvas
        self.canvas = tk.Canvas(
            main_frame, width=600, height=500,
            bg="#0a0a1a", highlightthickness=0
        )
        self.canvas.pack(side="left", fill="both", expand=True)
        
        # Create control panel
        control_frame = ttk.Frame(main_frame, width=150)
        control_frame.pack(side="right", fill="y", padx=(10, 0))
        
        # Load data button
        ttk.Button(
            control_frame, text="Load Silverstone Data",
            command=self.load_silverstone_data
        ).pack(pady=10)
        
        # Info label
        self.info_label = ttk.Label(
            control_frame, text="Click 'Load Silverstone Data'"
        )
        self.info_label.pack(pady=10)
        
        # Track data
        self.track_points = []
        self.player_trace = []
        self.current_pos = (0, 0)
        
        # Draw initial placeholder
        self.draw_placeholder()
        
        self.root.mainloop()
    
    def draw_placeholder(self):
        """Draw placeholder before loading data"""
        self.canvas.delete("all")
        
        # Draw title
        self.canvas.create_text(
            300, 50,
            text="SILVERSTONE TRACK MAP",
            fill="#e94560", font=("Arial", 16, "bold")
        )
        
        # Draw instructions
        self.canvas.create_text(
            300, 100,
            text="Click 'Load Silverstone Data' to load",
            fill="#4fc3f7", font=("Arial", 12)
        )
        self.canvas.create_text(
            300, 130,
            text="actual Silverstone track coordinates",
            fill="#4fc3f7", font=("Arial", 12)
        )
        
        # Draw sample track outline (Silverstone shape)
        # Simplified Silverstone outline
        points = []
        for i in range(100):
            angle = (i / 100) * 2 * np.pi
            # Silverstone-like shape
            r = 180 + 40 * np.sin(angle * 3) + 20 * np.sin(angle * 5)
            x = 300 + r * np.cos(angle)
            y = 250 + r * 0.6 * np.sin(angle)
            points.extend([x, y])
        
        self.canvas.create_line(
            *points, fill="#333333", width=3, smooth=True
        )
        
        # Draw legend
        self.canvas.create_text(50, 450, text="Grey: Track Outline", fill="#666666", anchor="w")
        self.canvas.create_text(50, 470, text="Blue: Racing Line", fill="#4fc3f7", anchor="w")
        self.canvas.create_text(50, 490, text="Red: Car Position", fill="#e94560", anchor="w")
    
    def load_silverstone_data(self):
        """Load actual Silverstone data from CSV files"""
        try:
            # Find a Silverstone CSV file
            csv_dir = "senna_ai/opponent_laps/Silverstone Grand Prix Circuit - ELMS"
            if not os.path.exists(csv_dir):
                self.info_label.config(text="CSV directory not found")
                return
            
            # Get first CSV file
            csv_files = [f for f in os.listdir(csv_dir) if f.endswith('.csv')]
            if not csv_files:
                self.info_label.config(text="No CSV files found")
                return
            
            csv_path = os.path.join(csv_dir, csv_files[0])
            
            # Read CSV (skip first few metadata rows)
            df = pd.read_csv(csv_path, skiprows=5)
            
            # Extract world coordinates
            if 'world_x' in df.columns and 'world_z' in df.columns:
                # Get every 10th point for performance
                track_points = []
                for i in range(0, len(df), 10):
                    x = df.iloc[i]['world_x']
                    z = df.iloc[i]['world_z']
                    track_points.append((x, z))
                
                self.track_points = track_points
                
                # Create a simple racing line (offset from track)
                self.player_trace = []
                for x, z in track_points[:len(track_points)//2]:  # First half
                    # Offset slightly for racing line
                    self.player_trace.append((x + 2, z))
                
                # Set current position
                if track_points:
                    self.current_pos = track_points[len(track_points)//4]
                
                self.info_label.config(text=f"Loaded {len(track_points)} points")
                self.draw_track_map()
            else:
                self.info_label.config(text="No coordinate data found")
                
        except Exception as e:
            self.info_label.config(text=f"Error: {str(e)}")
    
    def draw_track_map(self):
        """Draw the actual Silverstone track map"""
        if not self.track_points:
            return
        
        # Calculate bounds
        xs = [p[0] for p in self.track_points]
        zs = [p[1] for p in self.track_points]  # Using z as forward distance
        min_x, max_x = min(xs), max(xs)
        min_z, max_z = min(zs), max(zs)
        
        # Add margin
        margin_x = (max_x - min_x) * 0.1
        margin_z = (max_z - min_z) * 0.1
        bounds = (
            min_x - margin_x, max_x + margin_x,
            min_z - margin_z, max_z + margin_z
        )
        
        min_x, max_x, min_z, max_z = bounds
        
        # Clear canvas
        self.canvas.delete("all")
        
        # Draw track outline (grey)
        points = []
        for x, z in self.track_points:
            x_norm = (x - min_x) / (max_x - min_x)
            z_norm = (z - min_z) / (max_z - min_z)
            x_canvas = 20 + x_norm * 560
            z_canvas = 20 + (1 - z_norm) * 460  # Flip Z
            points.extend([x_canvas, z_canvas])
        
        if points:
            self.canvas.create_line(
                *points, fill="#666666", width=2, smooth=True
            )
        
        # Draw player trace (blue racing line)
        if self.player_trace:
            points = []
            for x, z in self.player_trace:
                x_norm = (x - min_x) / (max_x - min_x)
                z_norm = (z - min_z) / (max_z - min_z)
                x_canvas = 20 + x_norm * 560
                z_canvas = 20 + (1 - z_norm) * 460
                points.extend([x_canvas, z_canvas])
            
            if points:
                self.canvas.create_line(
                    *points, fill="#4fc3f7", width=1.5, smooth=True
                )
        
        # Draw current position (red dot)
        if self.current_pos:
            x, z = self.current_pos
            x_norm = (x - min_x) / (max_x - min_x)
            z_norm = (z - min_z) / (max_z - min_z)
            x_canvas = 20 + x_norm * 560
            z_canvas = 20 + (1 - z_norm) * 460
            
            self.canvas.create_oval(
                x_canvas - 5, z_canvas - 5,
                x_canvas + 5, z_canvas + 5,
                fill="#e94560", outline="white", width=1
            )
        
        # Add title
        self.canvas.create_text(
            300, 30,
            text="SILVERSTONE GRAND PRIX CIRCUIT",
            fill="#e94560", font=("Arial", 14, "bold")
        )
        
        # Add scale info
        track_length = max_z - min_z
        self.canvas.create_text(
            300, 480,
            text=f"Track length: {track_length:.0f}m",
            fill="#4fc3f7", font=("Arial", 10)
        )
        
        # Add legend
        self.canvas.create_text(50, 450, text="Grey: Track Outline", fill="#666666", anchor="w")
        self.canvas.create_text(50, 470, text="Blue: Racing Line", fill="#4fc3f7", anchor="w")
        self.canvas.create_text(50, 490, text="Red: Car Position", fill="#e94560", anchor="w")

if __name__ == "__main__":
    app = SilverstoneTrackMap()
