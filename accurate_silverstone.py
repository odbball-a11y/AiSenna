"""Accurate Silverstone track representation"""
import tkinter as tk
import numpy as np

class AccurateSilverstone:
    def __init__(self, parent, width=500, height=400):
        self.parent = parent
        self.width = width
        self.height = height
        
        # Create canvas with dark background
        self.canvas = tk.Canvas(
            parent, width=width, height=height,
            bg="#0a0a1a", highlightthickness=0
        )
        
        # Draw the track
        self._draw_silverstone()
        
    def pack(self, **kwargs):
        self.canvas.pack(**kwargs)
    
    def _draw_silverstone(self):
        """Draw accurate Silverstone track"""
        self.canvas.delete("all")
        
        # Silverstone track coordinates (simplified but recognizable)
        # Based on actual Silverstone layout
        track_points = []
        
        # Start/finish straight (Abbey)
        for i in range(20):
            x = -180 + i * 18
            y = -50
            track_points.append((x, y))
        
        # Farm curve
        for i in range(15):
            angle = np.pi/2 + (i/14) * np.pi/4
            x = 180 + 60 * np.cos(angle)
            y = -50 + 60 * np.sin(angle)
            track_points.append((x, y))
        
        # Wellington straight
        for i in range(15):
            x = 180 - i * 12
            y = 10 + i * 3
            track_points.append((x, y))
        
        # Brooklands/Luffield complex
        for i in range(25):
            angle = np.pi + (i/24) * np.pi/2
            x = 0 + 80 * np.cos(angle)
            y = 50 + 80 * np.sin(angle)
            track_points.append((x, y))
        
        # Woodcote/Club corner
        for i in range(15):
            angle = 3*np.pi/2 + (i/14) * np.pi/4
            x = -80 + 60 * np.cos(angle)
            y = 130 + 60 * np.sin(angle)
            track_points.append((x, y))
        
        # Hangar straight
        for i in range(25):
            x = -140 + i * 10
            y = 190
            track_points.append((x, y))
        
        # Stowe corner
        for i in range(20):
            angle = np.pi/2 + (i/19) * np.pi/2
            x = 100 + 90 * np.cos(angle)
            y = 190 + 90 * np.sin(angle)
            track_points.append((x, y))
        
        # Vale/Club entrance
        for i in range(15):
            x = 190 - i * 8
            y = 280 - i * 6
            track_points.append((x, y))
        
        # Chapel curve
        for i in range(20):
            angle = np.pi + (i/19) * np.pi/3
            x = 70 + 120 * np.cos(angle)
            y = 190 + 120 * np.sin(angle)
            track_points.append((x, y))
        
        # Maggotts/Becketts complex
        for i in range(30):
            angle = 4*np.pi/3 + (i/29) * np.pi/1.5
            x = -50 + 150 * np.cos(angle)
            y = 70 + 150 * np.sin(angle)
            track_points.append((x, y))
        
        # Copse corner
        for i in range(20):
            angle = 11*np.pi/6 + (i/19) * np.pi/3
            x = -200 + 100 * np.cos(angle)
            y = -80 + 100 * np.sin(angle)
            track_points.append((x, y))
        
        # Close the loop back to start/finish
        for i in range(10):
            x = -180 + i * 18
            y = -50
            track_points.append((x, y))
        
        # Scale and center the track
        xs = [p[0] for p in track_points]
        ys = [p[1] for p in track_points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        
        track_width = max_x - min_x
        track_height = max_y - min_y
        
        # Scale to fit canvas
        scale_x = (self.width - 100) / track_width
        scale_y = (self.height - 100) / track_height
        scale = min(scale_x, scale_y) * 0.9
        
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        
        # Convert to canvas coordinates
        canvas_points = []
        for x, y in track_points:
            x_canvas = (x - center_x) * scale + self.width / 2
            y_canvas = (y - center_y) * scale + self.height / 2
            canvas_points.extend([x_canvas, y_canvas])
        
        # Draw track outline (white/grey)
        if canvas_points:
            self.canvas.create_line(
                *canvas_points,
                fill="#CCCCCC",  # Light grey
                width=4,
                smooth=True,
                capstyle="round",
                joinstyle="round"
            )
        
        # Draw racing line (blue, slightly inside)
        racing_points = []
        n = len(track_points)
        for i in range(n):
            x, y = track_points[i]
            
            # Get surrounding points for normal calculation
            prev_idx = max(0, i-5)
            next_idx = min(n-1, i+5)
            
            prev_x, prev_y = track_points[prev_idx]
            next_x, next_y = track_points[next_idx]
            
            dx = next_x - prev_x
            dy = next_y - prev_y
            length = np.sqrt(dx*dx + dy*dy)
            
            if length > 0:
                # Normal vector (perpendicular)
                nx = -dy / length
                ny = dx / length
                # Racing line 3m inside track
                racing_points.append((x + nx * 3, y + ny * 3))
            else:
                racing_points.append((x, y))
        
        # Draw racing line
        racing_canvas = []
        for x, y in racing_points:
            x_canvas = (x - center_x) * scale + self.width / 2
            y_canvas = (y - center_y) * scale + self.height / 2
            racing_canvas.extend([x_canvas, y_canvas])
        
        if racing_canvas:
            self.canvas.create_line(
                *racing_canvas,
                fill="#4fc3f7",  # Bright blue
                width=2,
                smooth=True,
                capstyle="round"
            )
        
        # Draw car position (red)
        car_idx = 50  # Position on track
        if car_idx < len(racing_points):
            car_x, car_y = racing_points[car_idx]
            car_x_canvas = (car_x - center_x) * scale + self.width / 2
            car_y_canvas = (car_y - center_y) * scale + self.height / 2
            
            self.canvas.create_oval(
                car_x_canvas - 6, car_y_canvas - 6,
                car_x_canvas + 6, car_y_canvas + 6,
                fill="#e94560",
                outline="white",
                width=2
            )
        
        # Draw corner markers
        corners = [
            (0.05, "Copse", "C1"),
            (0.15, "Maggotts", "C2"),
            (0.25, "Becketts", "C3"),
            (0.35, "Chapel", "C4"),
            (0.45, "Stowe", "C5"),
            (0.55, "Vale", "C6"),
            (0.65, "Club", "C7"),
            (0.75, "Abbey", "C8"),
            (0.85, "Farm", "C9")
        ]
        
        for pos, name, label in corners:
            idx = int(pos * len(track_points))
            if idx < len(track_points):
                x, y = track_points[idx]
                x_canvas = (x - center_x) * scale + self.width / 2
                y_canvas = (y - center_y) * scale + self.height / 2
                
                # Corner marker
                self.canvas.create_oval(
                    x_canvas - 4, y_canvas - 4,
                    x_canvas + 4, y_canvas + 4,
                    fill="#53d769",
                    outline="white",
                    width=1
                )
                
                # Corner label
                self.canvas.create_text(
                    x_canvas, y_canvas - 10,
                    text=label,
                    fill="#53d769",
                    font=("Arial", 9, "bold")
                )
        
        # Draw title
        self.canvas.create_text(
            self.width / 2, 25,
            text="SILVERSTONE GRAND PRIX CIRCUIT",
            fill="#e94560",
            font=("Arial", 14, "bold")
        )
        
        # Draw info
        self.canvas.create_text(
            self.width / 2, self.height - 30,
            text="Length: 5.891 km • Laps: 52 • Fastest Lap: 1:27.097",
            fill="#4fc3f7",
            font=("Arial", 10)
        )
        
        # Draw legend at bottom
        legend_items = [
            (self.width * 0.2, "#CCCCCC", "Track", 4),
            (self.width * 0.35, "#4fc3f7", "Racing Line", 2),
            (self.width * 0.5, "#e94560", "Car", 0),
            (self.width * 0.65, "#53d769", "Corner", 0)
        ]
        
        legend_y = self.height - 10
        
        for x_pos, color, text, line_width in legend_items:
            if line_width > 0:
                self.canvas.create_line(
                    x_pos - 25, legend_y,
                    x_pos - 5, legend_y,
                    fill=color,
                    width=line_width,
                    capstyle="round"
                )
            else:
                if text == "Car":
                    self.canvas.create_oval(
                        x_pos - 20, legend_y - 4,
                        x_pos - 10, legend_y + 4,
                        fill=color,
                        outline="white",
                        width=1
                    )
                else:  # Corner
                    self.canvas.create_oval(
                        x_pos - 20, legend_y - 4,
                        x_pos - 10, legend_y + 4,
                        fill=color,
                        outline="white",
                        width=1
                    )
            
            self.canvas.create_text(
                x_pos, legend_y,
                text=text,
                fill=color,
                font=("Arial", 9),
                anchor="w"
            )

# Test
if __name__ == "__main__":
    root = tk.Tk()
    root.title("Accurate Silverstone Track")
    root.geometry("550x500")
    root.configure(bg="#1a1a2e")
    
    track = AccurateSilverstone(root, width=520, height=450)
    track.pack(pady=20)
    
    root.mainloop()
