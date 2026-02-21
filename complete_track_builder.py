"""Build complete track from multiple laps"""
import pandas as pd
import os
import numpy as np
import matplotlib.pyplot as plt
from scipy.spatial import KDTree

# Load and analyze Silverstone data
def analyze_silverstone():
    csv_dir = "senna_ai/opponent_laps/Silverstone Grand Prix Circuit - ELMS"
    csv_files = [f for f in os.listdir(csv_dir) if f.endswith('.csv')]
    
    print(f"Found {len(csv_files)} CSV files")
    
    # Load first 10 laps
    all_laps = []
    lap_lengths = []
    
    for i, csv_file in enumerate(csv_files[:10]):
        csv_path = os.path.join(csv_dir, csv_file)
        
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
        xs = df['world_x [m]'].values
        zs = df['world_z [m]'].values
        
        # Remove NaN
        points = []
        for x, z in zip(xs, zs):
            if not np.isnan(x) and not np.isnan(z):
                points.append((x, z))
        
        if points:
            all_laps.append(points)
            lap_lengths.append(len(points))
            print(f"Lap {i+1}: {len(points)} points")
    
    print(f"\nLoaded {len(all_laps)} laps")
    print(f"Average points per lap: {np.mean(lap_lengths):.0f}")
    print(f"Min points: {min(lap_lengths)}")
    print(f"Max points: {max(lap_lengths)}")
    
    # Analyze track coverage
    all_points = []
    for lap in all_laps:
        all_points.extend(lap)
    
    points_array = np.array(all_points)
    
    # Calculate bounds
    min_x, max_x = points_array[:, 0].min(), points_array[:, 0].max()
    min_z, max_z = points_array[:, 1].min(), points_array[:, 1].max()
    
    print(f"\nTrack bounds:")
    print(f"  X: {min_x:.1f} to {max_x:.1f} (width: {max_x-min_x:.1f}m)")
    print(f"  Z: {min_z:.1f} to {max_z:.1f} (height: {max_z-min_z:.1f}m)")
    
    # Create grid to check coverage
    grid_size = 20  # meters
    x_bins = int((max_x - min_x) / grid_size) + 1
    z_bins = int((max_z - min_z) / grid_size) + 1
    
    coverage_grid = np.zeros((z_bins, x_bins))
    
    for x, z in all_points:
        x_idx = int((x - min_x) / grid_size)
        z_idx = int((z - min_z) / grid_size)
        if 0 <= x_idx < x_bins and 0 <= z_idx < z_bins:
            coverage_grid[z_idx, x_idx] += 1
    
    coverage_percent = np.sum(coverage_grid > 0) / (x_bins * z_bins) * 100
    print(f"\nCoverage analysis:")
    print(f"  Grid cells: {x_bins}x{z_bins} = {x_bins*z_bins} cells")
    print(f"  Covered cells: {np.sum(coverage_grid > 0)} ({coverage_percent:.1f}%)")
    
    # Create complete track by combining laps
    complete_track = []
    
    # Use KDTree to find nearest points
    tree = KDTree(points_array)
    
    # Create grid of points to sample
    sample_resolution = 5  # meters
    x_samples = np.arange(min_x, max_x, sample_resolution)
    z_samples = np.arange(min_z, max_z, sample_resolution)
    
    # Sample points that are close to actual track points
    track_points = []
    for x in x_samples:
        for z in z_samples:
            # Find distance to nearest track point
            dist, idx = tree.query([x, z])
            if dist < 20:  # Within 20 meters of actual track
                track_points.append((x, z))
    
    print(f"\nGenerated {len(track_points)} track points")
    
    # Create visualization
    fig, axes = plt.subplots(2, 2, figsize=(14, 12))
    
    # Plot 1: Individual laps
    ax1 = axes[0, 0]
    colors = plt.cm.rainbow(np.linspace(0, 1, len(all_laps)))
    for i, lap in enumerate(all_laps):
        if lap:
            xs = [p[0] for p in lap]
            zs = [p[1] for p in lap]
            ax1.plot(xs, zs, color=colors[i], linewidth=0.5, alpha=0.5)
    ax1.set_title(f'Individual Laps ({len(all_laps)} laps)')
    ax1.set_xlabel('X (m)')
    ax1.set_ylabel('Z (m)')
    ax1.grid(True, alpha=0.3)
    ax1.axis('equal')
    ax1.invert_yaxis()
    
    # Plot 2: All points
    ax2 = axes[0, 1]
    ax2.scatter(points_array[:, 0], points_array[:, 1], 
               s=1, c='blue', alpha=0.1)
    ax2.set_title(f'All Points ({len(points_array):,} points)')
    ax2.set_xlabel('X (m)')
    ax2.set_ylabel('Z (m)')
    ax2.grid(True, alpha=0.3)
    ax2.axis('equal')
    ax2.invert_yaxis()
    
    # Plot 3: Coverage grid
    ax3 = axes[1, 0]
    im = ax3.imshow(coverage_grid, cmap='hot', 
                   extent=[min_x, max_x, max_z, min_z],  # Note: inverted for imshow
                   aspect='auto')
    ax3.set_title(f'Coverage Grid ({coverage_percent:.1f}% covered)')
    ax3.set_xlabel('X (m)')
    ax3.set_ylabel('Z (m)')
    plt.colorbar(im, ax=ax3, label='Point count')
    
    # Plot 4: Generated track
    ax4 = axes[1, 1]
    if track_points:
        track_array = np.array(track_points)
        ax4.scatter(track_array[:, 0], track_array[:, 1], 
                   s=1, c='green', alpha=0.5)
    ax4.set_title(f'Generated Track ({len(track_points)} points)')
    ax4.set_xlabel('X (m)')
    ax4.set_ylabel('Z (m)')
    ax4.grid(True, alpha=0.3)
    ax4.axis('equal')
    ax4.invert_yaxis()
    
    plt.tight_layout()
    plt.show()
    
    # Save track points
    if track_points:
        np.savetxt('silverstone_complete_track.csv', track_points, 
                   delimiter=',', header='x,z', comments='')
        print(f"\nComplete track saved to 'silverstone_complete_track.csv'")
    
    return track_points

if __name__ == "__main__":
    track_points = analyze_silverstone()
