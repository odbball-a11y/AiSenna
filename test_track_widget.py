"""Test the track map widget"""
import tkinter as tk
from tkinter import ttk
import sys
import os

# Add the senna_ai directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from senna_ai.ui.track_map_widget import TrackMapWidget

class TestApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Track Map Widget Test")
        self.root.geometry("800x600")
        
        # Create track map widget
        self.track_map = TrackMapWidget(self.root, width=400, height=300)
        self.track_map.pack(pady=20)
        
        # Create control buttons
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(pady=10)
        
        ttk.Button(btn_frame, text="Load Silverstone", 
                  command=lambda: self.load_track("Silverstone")).pack(side="left", padx=5)
        
        ttk.Button(btn_frame, text="Clear", 
                  command=self.track_map.clear).pack(side="left", padx=5)
        
        # Status label
        self.status = ttk.Label(self.root, text="Click 'Load Silverstone' to test")
        self.status.pack(pady=10)
        
        self.root.mainloop()
    
    def load_track(self, track_name):
        self.status.config(text=f"Loading {track_name}...")
        # Use the actual laps folder
        laps_folder = "senna_ai/opponent_laps"
        self.track_map.load_track_data(track_name, laps_folder)
        self.status.config(text=f"Loading {track_name} in background...")

if __name__ == "__main__":
    app = TestApp()
