"""Final track map with complete Silverstone track"""
import tkinter as tk
from tkinter import ttk
import numpy as np
import os

class FinalTrackMap:
    def __init__(self, parent, width=400, height=300):
        self.parent = parent
        self.width = width
        self.height = height
        
        # Create canvas
        self.canvas = tk.Canvas(
            parent, width=width, height=height,
            bg="#0a0a1a", highlightthickness=0
        )
        
        # Track data
        self.track_points = []
        self.racing_line = []
        self.current_pos = None
        self.track_name = "Silverstone"
        
        # Load pre-built track
        self._load_complete_track()
        
        # Draw track
        self._draw_track()
    
    def pack(self, **kwargs):
        """Pack the widget"""
        self.canvas.pack(**kwargs)
    
    def _load_complete_track(self):
        """Load complete track from CSV"""
        try:
            # Try to load the complete track we built
            if os.path.exists('silverstone_complete_track.csv'):
                data = np.loadtxt('silverstone_complete_track.csv', delimiter=',', skiprows=1)
                self.track_points = [(float(x), float(z)) for x, z in data]
                print(f"Loaded {len(self.track_points)} points from complete track")
            else:
                # Fallback: create simple Silverstone shape
                self._create_silverstone_shape()
                print("Created Silverstone shape (complete track not found)")
            
            # Create racing line (offset inward)
            self._create_racing_line()
            
            # Set current position
            if self.track_points:
                self.current_pos = self.track_points[0]
                
        except Exception as e:
            print(f"Error loading track: {e}")
            self._create_silverstone_shape()
    
    def _create_silverstone_shape(self):
        """Create Silverstone-shaped track"""
        # Silverstone-like shape parameters
        points = []
        n_points = 200
        
        for i in range(n_points):
            t = (i / n_points) * 2 * np.pi
            
            # Silverstone shape (simplified)
            r = 200 + 50 * np.sin(t * 3) + 30 * np.sin(t * 5) + 20 * np.sin(t * 7)
            x = r * np.cos(t)
            z = r * 0.7 * np.sin(t)
            
            # Add Silverstone's characteristic corners
            if 0.1 < (i / n_points) < 0.3:  # Maggotts/Becketts complex
                x += 20 * np.sin(t * 10)
                z += 10 * np.cos(t * 10)
            elif 0.4 < (i / n_points) < 0.6:  # Stowe corner
                x -= 30 * np.sin(t * 8)
            elif 0.7 < (i / n_points) < 0.9:  # Club corner
                z -= 20 * np.cos(t * 12)
            
            points.append((x, z))
        
        self.track_points = points
    
    def _create_racing_line(self):
        """Create racing line (offset inward from track)"""
        if not self.track_points:
            return
        
        self.racing_line = []
        n = len(self.track_points)
        
        for i in range(n):
            x, z = self.track_points[i]
            
            # Get previous and next points for normal calculation
            prev_x, prev_z = self.track_points[(i-1) % n]
            next_x, next_z = self.track_points[(i+1) % n]
            
            # Calculate tangent
            dx = next_x - prev_x
            dz = next_z - prev_z
            length = np.sqrt(dx*dx + dz*dz)
            
            if length > 0:
                # Normal vector (perpendicular to tangent)
                nx = -dz / length
                nz = dx / length
                
                # Offset inward by 5 meters
                self.racing_line.append((x + nx * 5, z + nz * 5))
            else:
                self.racing_line.append((x, z))
    
    def _draw_track(self):
        """Draw the complete track"""
        self.canvas.delete("all")
        
        if not self.track_points:
            return
        
        # Calculate bounds
        xs = [p[0] for p in self.track_points]
        zs = [p[1] for p in self.track_points]
        min_x, max_x = min(xs), max(xs)
        min_z, max_z = min(zs), max(zs)
        
        # Calculate scale to fit in canvas
        track_width = max_x - min_x
        track_height = max_z - min_z
        
        canvas_width = self.width - 40
        canvas_height = self.height - 60
        
        scale_x = canvas_width / track_width if track_width > 0 else 1
        scale_z = canvas_height / track_height if track_height > 0 else 1
        scale = min(scale_x, scale_z) * 0.8
        
        # Center track
        center_x = (min_x + max_x) / 2
        center_z = (min_z + max_z) / 2
        
        # Draw track outline
        points = []
        for x, z in self.track_points:
            x_canvas = (x - center_x) * scale + self.width / 2
            z_canvas = (z - center_z) * scale + self.height / 2
            z_canvas = self.height - z_canvas  # Flip Y
            points.extend([x_canvas, z_canvas])
        
        # Close the loop
        if points:
            points.extend([points[0], points[1]])
            self.canvas.create_line(
                *points, fill="#666666", width=3, smooth=True
            )
        
        # Draw racing line
        if self.racing_line:
            points = []
            for x, z in self.racing_line:
                x_canvas = (x - center_x) * scale + self.width / 2
                z_canvas = (z - center_z) * scale + self.height / 2
                z_canvas = self.height - z_canvas
                points.extend([x_canvas, z_canvas])
            
            if points:
                self.canvas.create_line(
                    *points, fill="#4fc3f7", width=2, smooth=True
                )
        
        # Draw current position
        if self.current_pos:
            x, z = self.current_pos
            x_canvas = (x - center_x) * scale + self.width / 2
            z_canvas = (z - center_z) * scale + self.height / 2
            z_canvas = self.height - z_canvas
            
            self.canvas.create_oval(
                x_canvas - 5, z_canvas - 5,
                x_canvas + 5, z_canvas + 5,
                fill="#e94560", outline="white", width=2
            )
        
        # Draw title
        self.canvas.create_text(
            self.width // 2, 20,
            text="SILVERSTONE GRAND PRIX",
            fill="#e94560", font=("Arial", 12, "bold")
        )
        
        # Draw corners
        corners = [
            (0.05, "Copse"), (0.15, "Maggotts"), (0.25, "Becketts"),
            (0.35, "Chapel"), (0.45, "Stowe"), (0.55, "Vale"),
            (0.65, "Club"), (0.75, "Abbey"), (0.85, "Farm"), (0.95, "Wellington")
        ]
        
        for pos, name in corners:
            idx = int(pos * len(self.track_points))
            if idx < len(self.track_points):
                x, z = self.track_points[idx]
                x_canvas = (x - center_x) * scale + self.width / 2
                z_canvas = (z - center_z) * scale + self.height / 2
                z_canvas = self.height - z_canvas
                
                self.canvas.create_text(
                    x_canvas, z_canvas,
                    text=name,
                    fill="#53d769", font=("Arial", 7, "bold")
                )
                
                self.canvas.create_oval(
                    x_canvas - 2, z_canvas - 2,
                    x_canvas + 2, z_canvas + 2,
                    fill="#53d769", outline=""
                )
        
        # Draw legend
        self.canvas.create_text(10, self.height - 40, text="Grey: Track", 
                               fill="#666666", anchor="w", font=("Arial", 8))
        self.canvas.create_text(10, self.height - 25, text="Blue: Racing Line", 
                               fill="#4fc3f7", anchor="w", font=("Arial", 8))
        self.canvas.create_text(10, self.height - 10, text="Red: Car Position", 
                               fill="#e94560", anchor="w", font=("Arial", 8))
        
        self.canvas.create_text(self.width - 10, self.height - 10, text="Green: Corners", 
                               fill="#53d769", anchor="e", font=("Arial", 8))
    
    def update_position(self, x: float, z: float):
        """Update car position"""
        self.current_pos = (x, z)
        self._draw_track()

# Test the widget
if __name__ == "__main__":
    root = tk.Tk()
    root.title("Silverstone Track Map")
    root.geometry("500x450")
    
    track_map = FinalTrackMap(root, width=450, height=400)
    track_map.pack(pady=10)
    
    # Test button to simulate position update
    def move_car():
        # Simulate moving around the track
        import time
        import math
        
        if track_map.track_points:
            n = len(track_map.track_points)
            for i in range(0, n, 5):
                x, z = track_map.track_points[i]
                track_map.update_position(x, z)
                root.update()
                root.after(50)  # Small delay
    
    btn = tk.Button(root, text="Simulate Lap", command=move_car)
    btn.pack(pady=10)
    
    root.mainloop()
