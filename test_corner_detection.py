#!/usr/bin/env python3
"""Test the new multi-apex corner detection."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
logging.basicConfig(level=logging.DEBUG, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

from senna_ai.telemetry.models import RefLapFile
from senna_ai.track.corner_detection import detect_corners

# Load a Silverstone lap
def test_silverstone():
    silverstone_file = "senna_ai/opponent_laps/Silverstone Grand Prix Circuit - ELMS/silverstone_grand_prix_circuit_-_elms_104.456s_ALE_L20_2026-02-18_232553_live.csv"
    
    if not os.path.exists(silverstone_file):
        print(f"File not found: {silverstone_file}")
        return
    
    print(f"Loading: {silverstone_file}")
    lap = RefLapFile(silverstone_file)
    
    print(f"Lap time: {lap.lap_time:.3f}s, Points: {len(lap.trace.points)}")
    
    # Detect corners with DEBUG logging enabled
    corners = detect_corners(lap.trace.points)
    
    print(f"\nDetected {len(corners)} corners:")
    for c in corners:
        zone_length = c.exit_m - c.brake_point_m
        print(f"  C{c.index}: brake@{c.brake_point_m:.0f}m -> apex@{c.apex_m:.0f}m ({c.apex_speed_kph:.0f}kph) -> exit@{c.exit_m:.0f}m (zone: {zone_length:.0f}m, max_brake: {c.max_brake_pct:.0f}%)")
    
    # Check for Maggots-Becketts area (900m-2400m)
    print(f"\n=== MAGGOTS-BECKETTS AREA (900m-2400m) ===")
    maggot_beckett_corners = [c for c in corners if 900 <= c.brake_point_m <= 2400]
    
    if maggot_beckett_corners:
        print(f"Found {len(maggot_beckett_corners)} corners in Maggots-Becketts area:")
        for c in maggot_beckett_corners:
            zone_length = c.exit_m - c.brake_point_m
            print(f"  C{c.index}: {c.brake_point_m:.0f}m-{c.exit_m:.0f}m ({zone_length:.0f}m), brake={c.max_brake_pct:.0f}%")
            
            # Check if this would trigger multi-apex detection
            if zone_length > 200 and c.max_brake_pct < 20:
                print(f"    ⚡ WOULD TRIGGER multi-apex detection!")
    else:
        print("No corners detected in Maggots-Becketts area!")
    
    # Also check the raw events to understand what's happening
    print(f"\n=== ANALYZING TELEMETRY IN MAGGOTS-BECKETTS ===")
    points_in_area = [p for p in lap.trace.points if 900 <= p.dist_m <= 2400]
    
    if points_in_area:
        # Check steering activity
        steering_points = [p for p in points_in_area if abs(p.steer_pct) > 4.8]  # 60% of 8.0
        print(f"Points in area: {len(points_in_area)}")
        print(f"Points with steering >4.8%: {len(steering_points)} ({len(steering_points)/len(points_in_area)*100:.0f}%)")
        
        # Check for continuous steering
        in_steering = False
        steering_start = None
        steering_zones = []
        
        for p in points_in_area:
            if abs(p.steer_pct) > 4.8:
                if not in_steering:
                    in_steering = True
                    steering_start = p.dist_m
            else:
                if in_steering:
                    in_steering = False
                    if p.dist_m - steering_start > 200:
                        steering_zones.append((steering_start, p.dist_m))
        
        if in_steering and points_in_area[-1].dist_m - steering_start > 200:
            steering_zones.append((steering_start, points_in_area[-1].dist_m))
        
        print(f"Continuous steering zones >200m: {len(steering_zones)}")
        for start, end in steering_zones:
            print(f"  Zone: {start:.0f}m - {end:.0f}m (length: {end-start:.0f}m)")

if __name__ == "__main__":
    test_silverstone()