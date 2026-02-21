"""Quick track visualization test"""
import matplotlib.pyplot as plt
import pandas as pd
import os
import numpy as np

# Load Silverstone data
csv_dir = "senna_ai/opponent_laps/Silverstone Grand Prix Circuit - ELMS"
csv_files = [f for f in os.listdir(csv_dir) if f.endswith('.csv')]

if csv_files:
    csv_path = os.path.join(csv_dir, csv_files[0])
    
    # Find header line
    with open(csv_path, 'r') as f:
        lines = f.readlines()
    
    header_line = None
    for i, line in enumerate(lines):
        if 'lapdistance' in line.lower():
            header_line = i
            break
    
    if header_line is not None:
        df = pd.read_csv(csv_path, skiprows=header_line)
        
        # Get coordinates
        xs = df['world_x [m]'].values[::5]  # Every 5th point
        zs = df['world_z [m]'].values[::5]
        
        # Create plot
        plt.figure(figsize=(10, 8))
        
        # Plot track
        plt.plot(xs, zs, 'w-', linewidth=2, alpha=0.7, label='Track')
        
        # Plot racing line (offset slightly)
        plt.plot(xs + 2, zs, 'c--', linewidth=1, alpha=0.5, label='Racing Line')
        
        # Plot car position
        mid_idx = len(xs) // 2
        plt.plot(xs[mid_idx], zs[mid_idx], 'ro', markersize=10, label='Car Position')
        
        # Format plot
        plt.gca().set_facecolor('black')
        plt.title('Silverstone Grand Prix Circuit', color='white', fontsize=16)
        plt.xlabel('X Position (m)', color='white')
        plt.ylabel('Z Position (m)', color='white')
        plt.legend(facecolor='black', edgecolor='white', labelcolor='white')
        plt.grid(True, alpha=0.3, color='gray')
        
        # Equal aspect ratio
        plt.axis('equal')
        
        # Invert Y axis for better visualization
        plt.gca().invert_yaxis()
        
        plt.tight_layout()
        plt.show()
        
        print(f"Plotted {len(xs)} points from {csv_files[0]}")
        print(f"X range: {xs.min():.1f} to {xs.max():.1f}")
        print(f"Z range: {zs.min():.1f} to {zs.max():.1f}")
    else:
        print("No header found")
else:
    print("No CSV files found")
