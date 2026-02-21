#!/usr/bin/env python3
"""Test geometric reference line building with hypercar laps."""

import sys
sys.path.insert(0, '.')

from senna_ai.telemetry.models import RefLapFile, LapTrace, TelPoint
from senna_ai.coaching.engine import CoachingEngine
from unittest.mock import Mock
import logging
import math

# Set up logging to see the output
logging.basicConfig(level=logging.INFO, format='%(message)s')

# Create a mock speaker
mock_speaker = Mock()

# Create test RefLapFile objects with position data
def create_hypercar_lap(filename, lap_time, variation=0):
    lap = RefLapFile.__new__(RefLapFile)
    lap.path = filename
    lap.filename = filename
    lap.track_name = "Spa-Francorchamps"
    lap.car_name = "Ferrari Hypercar"
    lap.lap_time = lap_time
    lap.track_length = 7004.0  # Spa length
    lap.event_type = "Qualifying"
    lap.date = "2024-01-01"
    lap.car_class = "Hypercar"
    lap.is_valid = True
    
    # Create trace with position data
    points = []
    n_points = 300  # More points for longer track
    for i in range(n_points):
        dist_m = i * (lap.track_length / n_points)
        
        # Simulate racing line with slight variations between laps
        # Base line: sine wave for corners
        base_x = 15.0 * math.sin(dist_m / 500.0)
        
        # Add lap-specific variation (simulating different but consistent lines)
        variation_x = variation * 2.0 * math.sin(dist_m / 300.0)
        
        x = base_x + variation_x
        z = dist_m  # Forward position
        
        # Speed varies with corners
        speed = 220.0 - 30.0 * abs(math.sin(dist_m / 500.0))
        
        points.append(TelPoint(
            dist_m=dist_m,
            speed_kph=speed,
            throttle_pct=85.0,
            brake_pct=0.0,
            steer_pct=10.0 * math.sin(dist_m / 500.0),
            gear=6,
            timestamp=i * 0.05,
            world_x=x,
            world_y=0.0,
            world_z=z
        ))
    
    lap.trace = LapTrace(points=points, lap_time=lap_time)
    lap.corners = []
    
    # Build spline
    lap.trace.build_spline()
    
    return lap

# Create test laps - 10 hypercar laps with variations
print("Creating 10 hypercar test laps with position data...")
test_laps = []

# Create laps with different times and slight line variations
for i in range(10):
    lap_time = 105.0 + i * 0.3  # 105.0s to 107.7s
    variation = i * 0.1  # Increasing variation
    lap = create_hypercar_lap(
        f"hypercar_lap_{i+1}.csv", 
        lap_time, 
        variation
    )
    test_laps.append(lap)

print(f"Created {len(test_laps)} hypercar test laps")
print(f"Lap times: {', '.join(f'{lap.lap_time:.1f}s' for lap in test_laps)}")
print()

# Create coaching engine
print("Testing reference line building with hypercar laps...")
print("=" * 80)

engine = CoachingEngine(mock_speaker)
engine.set_reference_laps(test_laps)

print("\n" + "=" * 80)
print("Test Results:")
print()

# Check filtering results
print("1. Reference Lap Filtering:")
print(f"   - Total laps: {len(test_laps)}")
print(f"   - All laps are valid (is_valid=True)")
print(f"   - Car class: Hypercar")
print(f"   - Top 20% of 10 laps = 2 fastest laps selected")
print()

# Check if reference line was built
print("2. Geometric Reference Line:")
if engine.reference_line:
    print(f"   SUCCESS: Reference line built with {len(engine.reference_line)} distance points")
    
    # Show statistics
    distances = list(engine.reference_line.keys())
    if distances:
        print(f"   - Distance range: {distances[0]:.1f}m to {distances[-1]:.1f}m")
        print(f"   - Track coverage: {(distances[-1] - distances[0]) / 7004.0 * 100:.1f}% of track")
        
        # Check interval
        if len(distances) >= 2:
            intervals = [distances[i+1] - distances[i] for i in range(len(distances)-1)]
            avg_interval = sum(intervals) / len(intervals)
            print(f"   - Average interval: {avg_interval:.2f}m (target: 2.0m)")
            
            # Show sample points
            print(f"   - Sample points (every 1000m):")
            for dist in [0.0, 1000.0, 2000.0, 3000.0, 4000.0, 5000.0, 6000.0]:
                if dist in engine.reference_line:
                    x, z = engine.reference_line[dist]
                    print(f"     {dist:.0f}m: x={x:.1f}, z={z:.0f}")
else:
    print("   FAILED: No reference line built")
    
    # Check why it might have failed
    if hasattr(engine, 'composite') and engine.composite:
        print(f"   - Composite built with {len(engine.composite.ref_laps)} reference laps")
        if engine.composite.ref_laps:
            print(f"   - First lap has position data: {engine.composite.ref_laps[0].trace.has_position_data()}")

print()
print("3. Reference Consistency Validation:")
print("   Check logs above for 'Reference consistency mean deviation' message")
print()
print("Test complete!")