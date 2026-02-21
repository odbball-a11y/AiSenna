#!/usr/bin/env python3
"""Test geometric reference line building with hypercars at Silverstone."""

import sys
sys.path.insert(0, '.')

from senna_ai.telemetry.models import RefLapFile, LapTrace, TelPoint
from senna_ai.coaching.engine import CoachingEngine
from unittest.mock import Mock
import logging
import math

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(message)s')

# Create mock speaker
mock_speaker = Mock()

# Create hypercar laps at Silverstone
def create_silverstone_hypercar_lap(lap_num, lap_time):
    lap = RefLapFile.__new__(RefLapFile)
    lap.path = f"hypercar_silverstone_{lap_num}.csv"
    lap.filename = f"hypercar_silverstone_{lap_num}.csv"
    lap.track_name = "Silverstone"
    lap.car_name = "Ferrari 499P"
    lap.lap_time = lap_time
    lap.track_length = 5891.0  # Silverstone length
    lap.event_type = "Practice"
    lap.date = "2024-01-01"
    lap.car_class = "Hypercar"
    lap.is_valid = True
    
    # Create realistic Silverstone racing line
    points = []
    n_points = 250
    
    for i in range(n_points):
        dist_m = i * (lap.track_length / n_points)
        
        # Simulate Silverstone corners with position data
        # Complex wave pattern for Silverstone's many corners
        t = dist_m / lap.track_length * 2 * math.pi
        
        # X position: racing line width variation
        x = 8.0 * (
            math.sin(t * 3) * 0.3 + 
            math.sin(t * 7) * 0.2 + 
            math.sin(t * 12) * 0.1
        )
        
        # Add small random variation between laps
        variation = (lap_num % 3) * 0.5  # 3 different line variations
        x += variation * math.sin(dist_m / 200.0)
        
        z = dist_m  # Forward distance
        
        # Speed profile for Silverstone
        base_speed = 220.0
        speed_variation = 40.0 * abs(math.sin(t * 5))
        speed = base_speed - speed_variation
        
        points.append(TelPoint(
            dist_m=dist_m,
            speed_kph=speed,
            throttle_pct=90.0 if speed > 180 else 60.0,
            brake_pct=20.0 if speed < 160 else 0.0,
            steer_pct=15.0 * math.sin(t * 3),
            gear=6 if speed > 200 else 5,
            timestamp=i * 0.04,
            world_x=x,
            world_y=0.0,
            world_z=z
        ))
    
    lap.trace = LapTrace(points=points, lap_time=lap_time)
    lap.corners = []
    
    # Build spline
    if lap.trace.has_position_data():
        lap.trace.build_spline()
    
    return lap

# Create 12 hypercar laps (enough for top 20% = 2-3 laps)
print("Creating 12 hypercar laps at Silverstone...")
test_laps = []

for i in range(12):
    lap_time = 88.5 + i * 0.25  # 88.5s to 91.25s
    lap = create_silverstone_hypercar_lap(i+1, lap_time)
    test_laps.append(lap)
    print(f"  Lap {i+1}: {lap_time:.2f}s, position data: {lap.trace.has_position_data()}")

print(f"\nCreated {len(test_laps)} hypercar laps")
print()

# Test the coaching engine
print("Testing CoachingEngine with hypercar reference laps...")
print("=" * 80)

engine = CoachingEngine(mock_speaker)
engine.set_reference_laps(test_laps)

print("\n" + "=" * 80)
print("RESULTS:")
print()

# Check what happened
if hasattr(engine, 'reference_line') and engine.reference_line:
    print("SUCCESS: Geometric reference line was built!")
    print(f"- Number of distance points: {len(engine.reference_line)}")
    
    distances = list(engine.reference_line.keys())
    if distances:
        print(f"- Distance range: {distances[0]:.0f}m to {distances[-1]:.0f}m")
        print(f"- Track coverage: {len(distances) * 2.0:.0f}m total")
        
        # Show a few key points
        print("\nSample reference line points:")
        check_points = [0, 1000, 2000, 3000, 4000, 5000]
        for dist in check_points:
            # Find closest distance
            closest = min(distances, key=lambda d: abs(d - dist))
            if abs(closest - dist) < 50:  # Within 50m
                x, z = engine.reference_line[closest]
                print(f"  {closest:.0f}m: x={x:.1f}, z={z:.0f}")
else:
    print("FAILED: No reference line built")
    
    # Debug why
    print("\nDebug information:")
    if hasattr(engine, 'composite'):
        if engine.composite:
            print(f"- Composite built with {len(engine.composite.ref_laps)} reference laps")
            if engine.composite.ref_laps:
                lap = engine.composite.ref_laps[0]
                print(f"- First lap has position data: {lap.trace.has_position_data()}")
                print(f"- First lap spline built: {bool(lap.trace._spline_dists)}")
        else:
            print("- No composite built (check corner detection)")
    else:
        print("- No composite attribute found")

print("\nTest complete!")