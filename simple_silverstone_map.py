"""Simple Silverstone track map test"""
import tkinter as tk
import pandas as pd
import os

# Create window
root = tk.Tk()
root.title("Silverstone Track Map")
root.geometry("700x600")

# Create canvas
canvas = tk.Canvas(root, width=600, height=500, bg="black")
canvas.pack(pady=10)

# Status label
status = tk.Label(root, text="Loading Silverstone data...", font=("Arial", 12))
status.pack()

def load_and_draw():
    try:
        # Find CSV file
        csv_dir = "senna_ai/opponent_laps/Silverstone Grand Prix Circuit - ELMS"
        csv_files = [f for f in os.listdir(csv_dir) if f.endswith('.csv')]
        
        if not csv_files:
            status.config(text="No CSV files found")
            return
        
        csv_path = os.path.join(csv_dir, csv_files[0])
        
        # Find header line
        with open(csv_path, 'r') as f:
            lines = f.readlines()
        
        header_line = None
        for i, line in enumerate(lines):
            if 'lapdistance' in line.lower():
                header_line = i
                break
        
        if header_line is None:
            status.config(text="No data header found")
            return
        
        # Read data
        df = pd.read_csv(csv_path, skiprows=header_line)
        
        # Check columns
        print(f"Columns: {list(df.columns)}")
        
        # Get coordinates
        x_col = 'world_x [m]'
        z_col = 'world_z [m]'
        
        if x_col not in df.columns or z_col not in df.columns:
            status.config(text=f"Missing columns. Found: {list(df.columns)}")
            return
        
        # Extract points (every 10th for performance)
        xs = df[x_col].values[::10]
        zs = df[z_col].values[::10]
        
        # Normalize to canvas
        min_x, max_x = xs.min(), xs.max()
        min_z, max_z = zs.min(), zs.max()
        
        # Clear canvas
        canvas.delete("all")
        
        # Draw track
        points = []
        for x, z in zip(xs, zs):
            x_norm = (x - min_x) / (max_x - min_x)
            z_norm = (z - min_z) / (max_z - min_z)
            
            x_canvas = 50 + x_norm * 500
            z_canvas = 50 + (1 - z_norm) * 400  # Flip Y
            
            points.extend([x_canvas, z_canvas])
        
        if points:
            canvas.create_line(*points, fill="white", width=2, smooth=True)
        
        # Draw title
        canvas.create_text(300, 30, text="SILVERSTONE", fill="red", font=("Arial", 16, "bold"))
        
        status.config(text=f"Loaded {len(xs)} points from {csv_files[0]}")
        
    except Exception as e:
        status.config(text=f"Error: {str(e)}")
        print(f"Error: {e}")

# Load button
load_btn = tk.Button(root, text="Load Silverstone Data", command=load_and_draw, font=("Arial", 12))
load_btn.pack(pady=10)

# Initial message
canvas.create_text(300, 250, text="Click 'Load Silverstone Data'\nto draw the track", 
                   fill="yellow", font=("Arial", 14), justify="center")

root.mainloop()
