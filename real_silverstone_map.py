"""Real Silverstone track map using actual CSV data"""
import tkinter as tk
import numpy as np
import os

class RealSilverstoneMap:
    def __init__(self, parent, width=500, height=450):
        self.parent = parent
        self.width = width
        self.height = height
        
        # Create canvas
        self.canvas = tk.Canvas(
            parent, width=width, height=height,
            bg="#0a0a1a", highlightthickness=0
        )
        
        # Load real track data
        self.track_points = self._load_real_track_data()
        
        # Draw the track
        if self.track_points:
            self._draw_real_track()
        else:
            self._draw_error()
        
    def pack(self, **kwargs):
        self.canvas.pack(**kwargs)
    
    def _load_real_track_data(self):
        """Load real Silverstone track data from CSV"""
        try:
            # Load the complete track we built earlier
            if os.path.exists('silverstone_complete_track.csv'):
                print("Loading complete track data...")
                data = np.loadtxt('silverstone_complete_track.csv', delimiter=',', skiprows=1)
                points = [(float(x), float(z)) for x, z in data]
                print(f"Loaded {len(points)} track points")
                return points
            else:
                print("Complete track file not found, creating from raw data...")
                # Fallback: load from raw CSV files
                return self._load_from_raw_csvs()
        except Exception as e:
            print(f"Error loading track data: {e}")
            return []
    
    def _load_from_raw_csvs(self):
        """Load track data from raw CSV files"""
        import pandas as pd
        
        csv_dir = "senna_ai/opponent_laps/Silverstone Grand Prix Circuit - ELMS"
        if not os.path.exists(csv_dir):
            print(f"CSV directory not found: {csv_dir}")
            return []
        
        csv_files = [f for f in os.listdir(csv_dir) if f.endswith('.csv')]
        if not csv_files:
            print("No CSV files found")
            return []
        
        all_points = []
        
        # Load first 5 laps
        for i, csv_file in enumerate(csv_files[:5]):
            csv_path = os.path.join(csv_dir, csv_file)
            
            try:
                # Find header line
                with open(csv_path, 'r') as f:
                    lines = f.readlines()
                
                header_line = None
                for j, line in enumerate(lines):
                    if 'lapdistance' in line.lower():
                        header_line = j
                        break
                
                if header_line is None:
                    continue
                
                df = pd.read_csv(csv_path, skiprows=header_line)
                
                # Get coordinates
                xs = df['world_x [m]'].values[::10]  # Sample every 10th point
                zs = df['world_z [m]'].values[::10]
                
                # Remove NaN and add points
                for x, z in zip(xs, zs):
                    if not np.isnan(x) and not np.isnan(z):
                        all_points.append((float(x), float(z)))
                
                print(f"Loaded lap {i+1}: {len(xs)} points")
                
            except Exception as e:
                print(f"Error loading {csv_file}: {e}")
        
        print(f"Total points loaded: {len(all_points)}")
        return all_points
    
    def _draw_real_track(self):
        """Draw real Silverstone track"""
        self.canvas.delete("all")
        
        if not self.track_points:
            return
        
        # Calculate bounds
        xs = [p[0] for p in self.track_points]
        zs = [p[1] for p in self.track_points]
        min_x, max_x = min(xs), max(xs)
        min_z, max_z = min(zs), max(zs)
        
        print(f"Track bounds: X({min_x:.0f},{max_x:.0f}) Z({min_z:.0f},{max_z:.0f})")
        
        # Calculate scale to fit canvas
        track_width = max_x - min_x
        track_height = max_z - min_z
        
        canvas_width = self.width - 60  # Padding
        canvas_height = self.height - 100  # Padding for labels
        
        scale_x = canvas_width / track_width if track_width > 0 else 1
        scale_z = canvas_height / track_height if track_height > 0 else 1
        scale = min(scale_x, scale_z) * 0.85  # 85% of available space
        
        # Center track
        center_x = (min_x + max_x) / 2
        center_z = (min_z + max_z) / 2
        
        # Draw track outline
        # Since we have scattered points, we need to create a continuous line
        # We'll sample points to create a smooth track
        
        # Create a simplified track by sampling
        n_samples = 300
        if len(self.track_points) > n_samples:
            # Sort points by angle for continuous line
            points_array = np.array(self.track_points)
            
            # Calculate center of points
            center = np.mean(points_array, axis=0)
            
            # Sort by angle
            angles = np.arctan2(points_array[:, 1] - center[1], 
                               points_array[:, 0] - center[0])
            sorted_indices = np.argsort(angles)
            sorted_points = points_array[sorted_indices]
            
            # Sample evenly
            indices = np.linspace(0, len(sorted_points)-1, n_samples, dtype=int)
            sampled_points = sorted_points[indices]
            
            track_line = [(float(x), float(z)) for x, z in sampled_points]
        else:
            track_line = self.track_points
        
        # Draw track (grey line)
        canvas_points = []
        for x, z in track_line:
            x_canvas = (x - center_x) * scale + self.width / 2
            z_canvas = (z - center_z) * scale + self.height / 2
            # Flip Z (racing games often have inverted Z)
            z_canvas = self.height - z_canvas
            canvas_points.extend([x_canvas, z_canvas])
        
        # Close the loop
        if canvas_points:
            canvas_points.extend([canvas_points[0], canvas_points[1]])
            self.canvas.create_line(
                *canvas_points,
                fill="#AAAAAA",  # Light grey
                width=3,
                smooth=True
            )
        
        # Draw racing line (blue, inside track)
        if track_line:
            racing_line = []
            n = len(track_line)
            
            for i in range(n):
                x, z = track_line[i]
                prev_x, prev_z = track_line[(i-1) % n]
                next_x, next_z = track_line[(i+1) % n]
                
                dx = next_x - prev_x
                dz = next_z - prev_z
                length = np.sqrt(dx*dx + dz*dz)
                
                if length > 0:
                    # Normal vector
                    nx = -dz / length
                    nz = dx / length
                    # Racing line 3m inside
                    racing_line.append((x + nx * 3, z + nz * 3))
                else:
                    racing_line.append((x, z))
            
            # Draw racing line
            racing_canvas = []
            for x, z in racing_line:
                x_canvas = (x - center_x) * scale + self.width / 2
                z_canvas = (z - center_z) * scale + self.height / 2
                z_canvas = self.height - z_canvas
                racing_canvas.extend([x_canvas, z_canvas])
            
            if racing_canvas:
                self.canvas.create_line(
                    *racing_canvas,
                    fill="#4fc3f7",  # Blue
                    width=2,
                    smooth=True
                )
            
            # Draw car position (red)
            car_idx = len(racing_line) // 4  # 1/4 around track
            car_x, car_z = racing_line[car_idx]
            car_x_canvas = (car_x - center_x) * scale + self.width / 2
            car_z_canvas = (car_z - center_z) * scale + self.height / 2
            car_z_canvas = self.height - car_z_canvas
            
            self.canvas.create_oval(
                car_x_canvas - 6, car_z_canvas - 6,
                car_x_canvas + 6, car_z_canvas + 6,
                fill="#e94560",  # Red
                outline="white",
                width=2
            )
        
        # Draw known Silverstone corners
        corners = [
            (0.05, "Copse"),
            (0.15, "Maggotts"),
            (0.25, "Becketts"),
            (0.35, "Chapel"),
            (0.45, "Stowe"),
            (0.55, "Vale"),
            (0.65, "Club"),
            (0.75, "Abbey"),
            (0.85, "Farm"),
            (0.95, "Wellington")
        ]
        
        if track_line:
            for pos, name in corners:
                idx = int(pos * len(track_line))
                if idx < len(track_line):
                    x, z = track_line[idx]
                    x_canvas = (x - center_x) * scale + self.width / 2
                    z_canvas = (z - center_z) * scale + self.height / 2
                    z_canvas = self.height - z_canvas
                    
                    # Corner marker
                    self.canvas.create_oval(
                        x_canvas - 4, z_canvas - 4,
                        x_canvas + 4, z_canvas + 4,
                        fill="#53d769",  # Green
                        outline="white",
                        width=1
                    )
                    
                    # Corner label (short name)
                    short_name = name[:3] if len(name) > 3 else name
                    self.canvas.create_text(
                        x_canvas, z_canvas - 10,
                        text=short_name,
                        fill="#53d769",
                        font=("Arial", 8, "bold")
                    )
        
        # Draw title
        self.canvas.create_text(
            self.width / 2, 25,
            text="SILVERSTONE (REAL DATA)",
            fill="#e94560",
            font=("Arial", 14, "bold")
        )
        
        # Draw stats
        stats_text = f"Points: {len(self.track_points):,} • Scale: {scale:.3f}"
        self.canvas.create_text(
            self.width / 2, self.height - 40,
            text=stats_text,
            fill="#4fc3f7",
            font=("Arial", 10)
        )
        
        bounds_text = f"X: {min_x:.0f}→{max_x:.0f}m • Z: {min_z:.0f}→{max_z:.0f}m"
        self.canvas.create_text(
            self.width / 2, self.height - 25,
            text=bounds_text,
            fill="#888888",
            font=("Arial", 9)
        )
        
        # Draw legend
        legend_y = self.height - 10
        
        # Track
        self.canvas.create_line(20, legend_y, 40, legend_y,
                               fill="#AAAAAA", width=3, capstyle="round")
        self.canvas.create_text(45, legend_y, text="Track",
                               fill="#AAAAAA", font=("Arial", 8), anchor="w")
        
        # Racing line
        self.canvas.create_line(90, legend_y, 110, legend_y,
                               fill="#4fc3f7", width=2, capstyle="round")
        self.canvas.create_text(115, legend_y, text="Racing Line",
                               fill="#4fc3f7", font=("Arial", 8), anchor="w")
        
        # Car
        self.canvas.create_oval(165, legend_y-3, 175, legend_y+3,
                               fill="#e94560", outline="white", width=1)
        self.canvas.create_text(180, legend_y, text="Car",
                               fill="#e94560", font=("Arial", 8), anchor="w")
        
        # Corner
        self.canvas.create_oval(210, legend_y-3, 220, legend_y+3,
                               fill="#53d769", outline="white", width=1)
        self.canvas.create_text(225, legend_y, text="Corner",
                               fill="#53d769", font=("Arial", 8), anchor="w")
    
    def _draw_error(self):
        """Draw error message"""
        self.canvas.delete("all")
        
        self.canvas.create_text(
            self.width / 2, self.height / 2,
            text="Error loading track data\nCheck CSV files exist",
            fill="#e94560",
            font=("Arial", 12),
            justify="center"
        )

# Test
if __name__ == "__main__":
    root = tk.Tk()
    root.title("Real Silverstone Track Map")
    root.geometry("550x500")
    root.configure(bg="#1a1a2e")
    
    track = RealSilverstoneMap(root, width=520, height=450)
    track.pack(pady=20)
    
    root.mainloop()
