#!/usr/bin/env python3
"""Analyze what's in the 1067m zone."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from senna_ai.telemetry.models import RefLapFile

# Load the lap
silverstone_file = "senna_ai/opponent_laps/Silverstone Grand Prix Circuit - ELMS/silverstone_grand_prix_circuit_-_elms_104.456s_ALE_L20_2026-02-18_232553_live.csv"
lap = RefLapFile(silverstone_file)

# Analyze the 239m-1306m zone
zone_start = 239
zone_end = 1306
zone_points = [p for p in lap.trace.points if zone_start <= p.dist_m <= zone_end]

print(f"Zone: {zone_start}m - {zone_end}m ({zone_end-zone_start:.0f}m)")
print(f"Points in zone: {len(zone_points)}")

# Check braking
braking_points = [p for p in zone_points if p.brake_pct > 8.0]
print(f"Points with brake >8%: {len(braking_points)}")

# Check steering
steering_points = [p for p in zone_points if abs(p.steer_pct) > 8.0]
print(f"Points with |steer| >8%: {len(steering_points)}")

# Find speed minima
min_speed = min(zone_points, key=lambda p: p.speed_kph)
print(f"\nMinimum speed: {min_speed.speed_kph:.0f}kph at {min_speed.dist_m:.0f}m")

# Check if there are multiple speed drops
print(f"\n=== SPEED ANALYSIS ===")
speeds = [p.speed_kph for p in zone_points]

# Find local minima
local_minima = []
for i in range(1, len(speeds) - 1):
    if speeds[i] < speeds[i-1] and speeds[i] < speeds[i+1]:
        if speeds[i] < speeds[0] - 15:  # Significant drop
            dist = zone_points[i].dist_m
            local_minima.append((dist, speeds[i]))

print(f"Found {len(local_minima)} local speed minima:")
for dist, speed in local_minima:
    print(f"  {dist:.0f}m: {speed:.0f}kph")

# Check steering peaks
print(f"\n=== STEERING PEAKS ===")
steering = [abs(p.steer_pct) for p in zone_points]
steering_peaks = []
for i in range(1, len(steering) - 1):
    if steering[i] > steering[i-1] and steering[i] > steering[i+1]:
        if steering[i] > 4.8:  # 60% of 8.0
            dist = zone_points[i].dist_m
            steering_peaks.append((dist, steering[i]))

print(f"Found {len(steering_peaks)} steering peaks >4.8%:")
for dist, steer in steering_peaks[:10]:  # Show first 10
    print(f"  {dist:.0f}m: {steer:.1f}%")
if len(steering_peaks) > 10:
    print(f"  ... and {len(steering_peaks)-10} more")

# Check brake application
print(f"\n=== BRAKE APPLICATION ===")
brake_changes = []
current_brake = zone_points[0].brake_pct
for p in zone_points:
    if abs(p.brake_pct - current_brake) > 20:  # Significant change
        brake_changes.append((p.dist_m, current_brake, p.brake_pct))
        current_brake = p.brake_pct

print(f"Significant brake changes (>20% difference): {len(brake_changes)}")
for dist, old_brake, new_brake in brake_changes:
    print(f"  {dist:.0f}m: {old_brake:.0f}% -> {new_brake:.0f}%")

# Silverstone corners in this zone (approx):
# 240m: Village/The Loop
# 360m: Apex of Village
# 916m: Maggots entry (should be brake point)
# 1277m: Maggots apex
# 1340m: Maggots exit
# 2149m: Becketts entry brake
# 2350m: Becketts apex
# 2379m: Becketts exit
print(f"\n=== EXPECTED SILVERSTONE CORNERS IN ZONE ===")
expected = [
    (360, "Village apex"),
    (1277, "Maggots apex"),
    (2350, "Becketts apex"),
]
for dist, name in expected:
    if zone_start <= dist <= zone_end:
        print(f"  {dist:.0f}m: {name} (INSIDE zone)")
    else:
        print(f"  {dist:.0f}m: {name} (OUTSIDE zone)")