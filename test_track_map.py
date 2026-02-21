"""Test track map visualization"""
import tkinter as tk
from tkinter import ttk
import math

class TrackMapTest:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Track Map Test")
        self.root.geometry("500x500")
        self.root.configure(bg="#1a1a2e")
        
        # Create canvas
        self.canvas = tk.Canvas(
            self.root, width=400, height=400,
            bg="#0a0a1a", highlightthickness=0
        )
        self.canvas.pack(pady=20)
        
        # Create test data
        self.create_test_data()
        
        # Draw
        self.draw_track_map()
        
        self.root.mainloop()
    
    def create_test_data(self):
        """Create a simple oval track for testing"""
        # Reference line (oval track)
        self.reference_line = []
        for i in range(100):
            angle = (i / 100) * 2 * math.pi
            x = 200 + 150 * math.cos(angle)
            y = 200 + 100 * math.sin(angle)
            self.reference_line.append((x, y))
        
        # Player trace (slightly offset)
        self.player_trace = []
        for i in range(50):
            angle = (i / 50) * 2 * math.pi
            x = 200 + 140 * math.cos(angle)
            y = 200 + 90 * math.sin(angle)
            self.player_trace.append((x, y))
        
        # Current position
        self.current_pos = (200 + 140, 200)  # Right side of track
    
    def draw_track_map(self):
        """Draw the track map"""
        # Calculate bounds
        xs = [p[0] for p in self.reference_line]
        ys = [p[1] for p in self.reference_line]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        
        # Add margin
        margin_x = (max_x - min_x) * 0.1
        margin_y = (max_y - min_y) * 0.1
        bounds = (
            min_x - margin_x, max_x + margin_x,
            min_y - margin_y, max_y + margin_y
        )
        
        min_x, max_x, min_y, max_y = bounds
        
        # Clear canvas
        self.canvas.delete("all")
        
        # Draw reference line (grey)
        points = []
        for x, y in self.reference_line:
            x_norm = (x - min_x) / (max_x - min_x)
            y_norm = (y - min_y) / (max_y - min_y)
            x_canvas = 10 + x_norm * 380
            y_canvas = 10 + (1 - y_norm) * 380  # Flip Y
            points.extend([x_canvas, y_canvas])
        
        if points:
            self.canvas.create_line(
                *points, fill="#666666", width=2, smooth=True
            )
        
        # Draw player trace (blue)
        points = []
        for x, y in self.player_trace:
            x_norm = (x - min_x) / (max_x - min_x)
            y_norm = (y - min_y) / (max_y - min_y)
            x_canvas = 10 + x_norm * 380
            y_canvas = 10 + (1 - y_norm) * 380
            points.extend([x_canvas, y_canvas])
        
        if points:
            self.canvas.create_line(
                *points, fill="#4fc3f7", width=1.5, smooth=True
            )
        
        # Draw current position (red dot)
        x, y = self.current_pos
        x_norm = (x - min_x) / (max_x - min_x)
        y_norm = (y - min_y) / (max_y - min_y)
        x_canvas = 10 + x_norm * 380
        y_canvas = 10 + (1 - y_norm) * 380
        
        self.canvas.create_oval(
            x_canvas - 4, y_canvas - 4,
            x_canvas + 4, y_canvas + 4,
            fill="#e94560", outline="white", width=1
        )
        
        # Add label
        self.canvas.create_text(
            200, 20,
            text="TRACK MAP TEST",
            fill="#e94560", font=("Arial", 12, "bold")
        )
        
        # Add legend
        self.canvas.create_text(50, 380, text="Grey: Reference", fill="#666666", anchor="w")
        self.canvas.create_text(50, 400, text="Blue: Player", fill="#4fc3f7", anchor="w")
        self.canvas.create_text(50, 420, text="Red: Position", fill="#e94560", anchor="w")

if __name__ == "__main__":
    app = TrackMapTest()
