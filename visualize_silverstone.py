"""Visualize Silverstone track coordinates"""
import pandas as pd
import os
import matplotlib.pyplot as plt
import numpy as np

# Load Silverstone data
csv_dir = "senna_ai/opponent_laps/Silverstone Grand Prix Circuit - ELMS"
csv_files = [f for f in os.listdir(csv_dir) if f.endswith('.csv')]

print(f"Found {len(csv_files)} CSV files")

# Load first 3 laps
all_points = []
for i in range(3):
    csv_path = os.path.join(csv_dir, csv_files[i])
    
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
    xs = df['world_x [m]'].values[::10]  # Every 10th point
    zs = df['world_z [m]'].values[::10]
    
    # Remove NaN
    points = []
    for x, z in zip(xs, zs):
        if not np.isnan(x) and not np.isnan(z):
            points.append((x, z))
    
    all_points.append(points)
    print(f"Lap {i+1}: {len(points)} points")

# Create plot
plt.figure(figsize=(12, 10))

# Plot each lap
colors = ['red', 'green', 'blue']
for i, points in enumerate(all_points):
    if points:
        xs = [p[0] for p in points]
        zs = [p[1] for p in points]
        plt.plot(xs, zs, color=colors[i], linewidth=1, alpha=0.7, label=f'Lap {i+1}')

# Calculate bounds
all_xs = []
all_zs = []
for points in all_points:
    for x, z in points:
        all_xs.append(x)
        all_zs.append(z)

min_x, max_x = min(all_xs), max(all_xs)
min_z, max_z = min(all_zs), max(all_zs)

# Add grid
plt.grid(True, alpha=0.3)
plt.axis('equal')

# Invert Y axis (typical for racing games)
plt.gca().invert_yaxis()

plt.title(f'Silverstone Track - {len(all_points)} Laps', fontsize=16)
plt.xlabel('X Position (m)')
plt.ylabel('Z Position (m)')
plt.legend()

# Add info text
info = f'''Track Bounds:
X: {min_x:.0f} to {max_x:.0f}m
Z: {min_z:.0f} to {max_z:.0f}m
Total points: {sum(len(p) for p in all_points)}'''

plt.text(0.02, 0.98, info, transform=plt.gca().transAxes,
         fontsize=10, verticalalignment='top',
         bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

plt.tight_layout()
plt.show()

print(f"\nTrack bounds: X({min_x:.0f}, {max_x:.0f}), Z({min_z:.0f}, {max_z:.0f})")
print(f"Track appears to be centered around ({np.mean(all_xs):.0f}, {np.mean(all_zs):.0f})")
