"""Proper track map with correct colors and legible corners"""
import tkinter as tk
import numpy as np

class ProperTrackMap:
    def __init__(self, parent, width=400, height=400):
        self.parent = parent
        self.width = width
        self.height = height
        
        # Create canvas
        self.canvas = tk.Canvas(
            parent, width=width, height=height,
            bg="#0a0a1a", highlightthickness=0
        )
        
        # Draw track
        self._draw_proper_silverstone()
        
    def pack(self, **kwargs):
        self.canvas.pack(**kwargs)
    
    def _draw_proper_silverstone(self):
        """Draw proper Silverstone track"""
        self.canvas.delete("all")
        
        # Create Silverstone track outline
        points = []
        n_points = 300
        
        for i in range(n_points):
            t = (i / n_points) * 2 * np.pi
            
            # Main oval shape
            r = 170
            
            # Add Silverstone's characteristic shape
            # Copse (right-hand turn)
            if 0.0 < t < 0.3:
                r += 30 * np.sin(t * 5)
            # Maggotts/Becketts complex (fast left-right-left)
            elif 0.3 < t < 0.5:
                r += 40 * np.sin((t-0.3) * 15)
            # Chapel curve (right)
            elif 0.5 < t < 0.6:
                r -= 20
            # Stowe corner (left)
            elif 0.6 < t < 0.7:
                r += 25 * np.sin((t-0.6) * 10)
            # Vale/Club complex (slow right-left)
            elif 0.7 < t < 0.9:
                r += 30 * np.sin((t-0.7) * 8)
            # Abbey/Farm/Wellington straight
            elif 0.9 < t < 1.0:
                r -= 15
            
            x = r * np.cos(t)
            y = r * 0.7 * np.sin(t)
            
            points.append((x, y))
        
        # Calculate bounds and scale
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        
        width = max_x - min_x
        height = max_y - min_y
        
        scale = min(self.width / width, self.height / height) * 0.8
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        
        # Convert to canvas coordinates
        canvas_points = []
        for x, y in points:
            x_canvas = (x - center_x) * scale + self.width / 2
            y_canvas = (y - center_y) * scale + self.height / 2
            canvas_points.extend([x_canvas, y_canvas])
        
        # Draw track outline (WHITE/GREY line)
        if canvas_points:
            # Close the loop
            canvas_points.extend([canvas_points[0], canvas_points[1]])
            self.canvas.create_line(
                *canvas_points, 
                fill="#AAAAAA",  # Light grey for track outline
                width=4, 
                smooth=True,
                capstyle="round",
                joinstyle="round"
            )
        
        # Draw racing line (BLUE line ON the track)
        racing_points = []
        n = len(points)
        for i in range(n):
            x, y = points[i]
            prev_x, prev_y = points[(i-1) % n]
            next_x, next_y = points[(i+1) % n]
            
            dx = next_x - prev_x
            dy = next_y - prev_y
            length = np.sqrt(dx*dx + dy*dy)
            
            if length > 0:
                # Normal vector
                nx = -dy / length
                ny = dx / length
                # Racing line is 2 meters inside track edge
                racing_points.append((x + nx * 2, y + ny * 2))
            else:
                racing_points.append((x, y))
        
        # Draw racing line
        racing_canvas_points = []
        for x, y in racing_points:
            x_canvas = (x - center_x) * scale + self.width / 2
            y_canvas = (y - center_y) * scale + self.height / 2
            racing_canvas_points.extend([x_canvas, y_canvas])
        
        if racing_canvas_points:
            self.canvas.create_line(
                *racing_canvas_points, 
                fill="#4fc3f7",  # Bright blue
                width=2, 
                smooth=True,
                capstyle="round"
            )
        
        # Draw car position (RED dot on racing line)
        car_x, car_y = racing_points[0]  # Start at first point
        car_x_canvas = (car_x - center_x) * scale + self.width / 2
        car_y_canvas = (car_y - center_y) * scale + self.height / 2
        
        self.canvas.create_oval(
            car_x_canvas - 6, car_y_canvas - 6,
            car_x_canvas + 6, car_y_canvas + 6,
            fill="#e94560",  # Bright red
            outline="white",
            width=2
        )
        
        # Draw corner markers with labels (GREEN)
        corners = [
            (0.02, "Copse", "C1"),
            (0.12, "Maggotts", "C2"),
            (0.22, "Becketts", "C3"),
            (0.32, "Chapel", "C4"),
            (0.42, "Stowe", "C5"),
            (0.52, "Vale", "C6"),
            (0.62, "Club", "C7"),
            (0.72, "Abbey", "C8"),
            (0.82, "Farm", "C9"),
            (0.92, "Wellington", "C10")
        ]
        
        for pos, name, short_name in corners:
            idx = int(pos * len(points))
            if idx < len(points):
                x, y = points[idx]
                x_canvas = (x - center_x) * scale + self.width / 2
                y_canvas = (y - center_y) * scale + self.height / 2
                
                # Draw corner marker
                self.canvas.create_oval(
                    x_canvas - 5, y_canvas - 5,
                    x_canvas + 5, y_canvas + 5,
                    fill="#53d769",  # Bright green
                    outline="white",
                    width=1
                )
                
                # Draw corner label
                # Position label outside the track
                label_x = x_canvas
                label_y = y_canvas - 15  # Above the marker
                
                # Adjust position for certain corners
                if name in ["Copse", "Stowe", "Club"]:
                    label_y = y_canvas + 15  # Below for these
                elif name in ["Becketts", "Abbey"]:
                    label_x = x_canvas + 15  # Right side
                elif name in ["Chapel", "Farm"]:
                    label_x = x_canvas - 15  # Left side
                
                self.canvas.create_text(
                    label_x, label_y,
                    text=short_name,
                    fill="#53d769",
                    font=("Arial", 9, "bold"),
                    anchor="center"
                )
                
                # Optional: full name for major corners
                if name in ["Copse", "Becketts", "Stowe", "Club"]:
                    self.canvas.create_text(
                        label_x, label_y + 12,
                        text=name,
                        fill="#AAAAAA",
                        font=("Arial", 7),
                        anchor="center"
                    )
        
        # Draw title
        self.canvas.create_text(
            self.width / 2, 20,
            text="SILVERSTONE GP",
            fill="#e94560",
            font=("Arial", 14, "bold")
        )
        
        # Draw length
        self.canvas.create_text(
            self.width / 2, self.height - 30,
            text="5.891 km • 18 Corners",
            fill="#4fc3f7",
            font=("Arial", 10)
        )
        
        # Draw simple legend
        legend_y = self.height - 10
        
        # Grey: Track
        self.canvas.create_line(
            20, legend_y, 40, legend_y,
            fill="#AAAAAA", width=4, capstyle="round"
        )
        self.canvas.create_text(
            55, legend_y,
            text="Track",
            fill="#AAAAAA",
            font=("Arial", 8),
            anchor="w"
        )
        
        # Blue: Racing Line
        self.canvas.create_line(
            100, legend_y, 120, legend_y,
            fill="#4fc3f7", width=2, capstyle="round"
        )
        self.canvas.create_text(
            125, legend_y,
            text="Racing Line",
            fill="#4fc3f7",
            font=("Arial", 8),
            anchor="w"
        )
        
        # Red: Car
        self.canvas.create_oval(
            180, legend_y - 3, 190, legend_y + 3,
            fill="#e94560", outline="white", width=1
        )
        self.canvas.create_text(
            195, legend_y,
            text="Car",
            fill="#e94560",
            font=("Arial", 8),
            anchor="w"
        )
        
        # Green: Corner
        self.canvas.create_oval(
            220, legend_y - 3, 230, legend_y + 3,
            fill="#53d769", outline="white", width=1
        )
        self.canvas.create_text(
            235, legend_y,
            text="Corner",
            fill="#53d769",
            font=("Arial", 8),
            anchor="w"
        )

# Test the widget
if __name__ == "__main__":
    root = tk.Tk()
    root.title("Proper Silverstone Track Map")
    root.geometry("450x450")
    root.configure(bg="#1a1a2e")
    
    track_map = ProperTrackMap(root, width=420, height=420)
    track_map.pack(pady=10)
    
    root.mainloop()
