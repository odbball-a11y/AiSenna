"""Build complete Silverstone track from multiple laps"""
import pandas as pd
import os
import numpy as np
import matplotlib.pyplot as plt
from scipy import spatial

# Load multiple Silverstone laps
def load_lap_data(csv_path):
    """Load a single lap from CSV"""
    # Find header line
    with open(csv_path, 'r') as f:
        lines = f.readlines()
    
    header_line = None
    for i, line in enumerate(lines):
        if 'lapdistance' in line.lower():
            header_line = i
            break
    
    if header_line is None:
        return None
    
    df = pd.read_csv(csv_path, skiprows=header_line)
    
    # Get coordinates
    xs = df['world_x [m]'].values
    zs = df['world_z [m]'].values
    
    return np.column_stack([xs, zs])

# Combine multiple laps
def combine_laps(lap_points_list):
    """Combine points from multiple laps"""
    all_points = []
    
    for lap_points in lap_points_list:
        if lap_points is not None and len(lap_points) > 0:
            # Sample points evenly
            indices = np.linspace(0, len(lap_points)-1, min(200, len(lap_points)), dtype=int)
            all_points.extend(lap_points[indices])
    
    if not all_points:
        return None
    
    return np.array(all_points)

# Create track outline from points
def create_track_outline(points, num_points=500):
    """Create smooth track outline from scattered points"""
    if points is None or len(points) < 10:
        return None
    
    # Use convex hull for outer boundary
    hull = spatial.ConvexHull(points)
    hull_points = points[hull.vertices]
    
    # Sort points by angle for smooth outline
    center = np.mean(hull_points, axis=0)
    angles = np.arctan2(hull_points[:, 1] - center[1], hull_points[:, 0] - center[0])
    sorted_indices = np.argsort(angles)
    
    # Create closed polygon
    outline = hull_points[sorted_indices]
    outline = np.vstack([outline, outline[0]])  # Close the loop
    
    return outline

# Main function
def main():
    csv_dir = "senna_ai/opponent_laps/Silverstone Grand Prix Circuit - ELMS"
    csv_files = [f for f in os.listdir(csv_dir) if f.endswith('.csv')]
    
    print(f"Found {len(csv_files)} CSV files")
    
    # Load first 10 laps (or all if less)
    num_laps_to_load = min(10, len(csv_files))
    lap_data = []
    
    for i in range(num_laps_to_load):
        csv_path = os.path.join(csv_dir, csv_files[i])
        print(f"Loading lap {i+1}: {csv_files[i]}")
        
        points = load_lap_data(csv_path)
        if points is not None:
            lap_data.append(points)
            print(f"  Loaded {len(points)} points")
        else:
            print(f"  Failed to load")
    
    print(f"\nSuccessfully loaded {len(lap_data)} laps")
    
    if not lap_data:
        print("No lap data loaded")
        return
    
    # Combine all laps
    combined_points = combine_laps(lap_data)
    
    if combined_points is None:
        print("Failed to combine laps")
        return
    
    print(f"Combined {len(combined_points)} points from all laps")
    
    # Create track outline
    track_outline = create_track_outline(combined_points)
    
    if track_outline is None:
        print("Failed to create track outline")
        return
    
    print(f"Created track outline with {len(track_outline)} points")
    
    # Create visualization
    plt.figure(figsize=(12, 10))
    
    # Plot individual lap points (transparent)
    colors = plt.cm.rainbow(np.linspace(0, 1, len(lap_data)))
    for i, lap_points in enumerate(lap_data):
        if len(lap_points) > 0:
            plt.plot(lap_points[:, 0], lap_points[:, 1], '.', 
                    color=colors[i], alpha=0.2, markersize=1, 
                    label=f'Lap {i+1}' if i < 5 else None)
    
    # Plot combined points
    plt.plot(combined_points[:, 0], combined_points[:, 1], 'w.', 
             alpha=0.3, markersize=2, label='All Points')
    
    # Plot track outline
    plt.plot(track_outline[:, 0], track_outline[:, 1], 'c-', 
             linewidth=3, alpha=0.8, label='Track Outline')
    
    # Plot racing line (median of all laps)
    racing_line = np.median(combined_points.reshape(-1, 2), axis=0)
    plt.plot(racing_line[0], racing_line[1], 'yo', 
             markersize=15, label='Racing Line Center')
    
    # Format plot
    plt.gca().set_facecolor('black')
    plt.title(f'Silverstone Track - {len(lap_data)} Laps Combined', 
              color='white', fontsize=18, pad=20)
    plt.xlabel('X Position (m)', color='white', fontsize=12)
    plt.ylabel('Z Position (m)', color='white', fontsize=12)
    
    # Legend
    if len(lap_data) <= 5:
        plt.legend(facecolor='black', edgecolor='white', labelcolor='white', 
                  loc='upper right', fontsize=10)
    
    plt.grid(True, alpha=0.2, color='gray')
    
    # Equal aspect ratio
    plt.axis('equal')
    
    # Invert Y axis (typical racing game coordinate system)
    plt.gca().invert_yaxis()
    
    # Add info text
    info_text = f'''Track Statistics:
• Laps used: {len(lap_data)}
• Total points: {len(combined_points)}
• Track length: ~{len(track_outline)} segments
• X range: {combined_points[:, 0].min():.0f} to {combined_points[:, 0].max():.0f}m
• Z range: {combined_points[:, 1].min():.0f} to {combined_points[:, 1].max():.0f}m'''
    
    plt.text(0.02, 0.98, info_text, transform=plt.gca().transAxes,
             fontsize=10, color='white', verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='black', alpha=0.7))
    
    plt.tight_layout()
    plt.show()
    
    # Save track outline to file
    np.savetxt('silverstone_track_outline.csv', track_outline, 
               delimiter=',', header='x,z', comments='')
    print(f"\nTrack outline saved to 'silverstone_track_outline.csv'")

if __name__ == "__main__":
    main()
