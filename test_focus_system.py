"""Test the focus turn coaching system"""
import tkinter as tk
from senna_ai.coaching.engine import CoachingEngine
from senna_ai.infra.tts_engine import Speaker
import time

# Mock speaker
class MockSpeaker:
    def __init__(self):
        self.messages = []
    def say(self, msg):
        print(f"SAY: {msg}")
        self.messages.append(msg)
    def say_priority(self, msg):
        print(f"SAY_PRIORITY: {msg}")
        self.messages.append(msg)
    def stop(self):
        pass

# Test
speaker = MockSpeaker()
engine = CoachingEngine(speaker)

print("Testing Focus Turn Coaching System")
print("=" * 50)

# Test 1: Initialization
print(f"1. Initial focus_turn_count: {engine.focus_turn_count}")
print(f"   focus_turns: {engine.focus_turns}")
print(f"   turn_focus_data: {engine.turn_focus_data}")

# Test 2: Simulate sector results
from senna_ai.track.corner_detection import SectorResult

# Create mock sector results with time losses
engine.sector_results = [
    SectorResult(sector_idx=1, time=15.5, delta_to_target=0.8, 
                brake_grade="poor", turn_in_grade="ok", apex_grade="good", exit_grade="ok"),
    SectorResult(sector_idx=2, time=12.2, delta_to_target=0.3, 
                brake_grade="good", turn_in_grade="poor", apex_grade="ok", exit_grade="good"),
    SectorResult(sector_idx=3, time=18.1, delta_to_target=1.2, 
                brake_grade="ok", turn_in_grade="good", apex_grade="poor", exit_grade="poor"),
]

# Test selection
engine._select_focus_turns()
print(f"\n2. After selection (count={engine.focus_turn_count}):")
print(f"   focus_turns: {engine.focus_turns}")
print(f"   turn_focus_data: {engine.turn_focus_data}")

# Test 3: Change focus turn count
engine.focus_turn_count = 2
engine._select_focus_turns()
print(f"\n3. After changing to 2 focus turns:")
print(f"   focus_turns: {engine.focus_turns}")

# Test 4: Test cue generation
print("\n4. Cue phrases for different correction types:")
corrections = [
    (1, {"correction_type": "brake_late", "distance_delta_m": 6.0}),
    (2, {"correction_type": "turn_in_late", "distance_delta_m": 5.0}),
    (3, {"correction_type": "release_earlier", "distance_delta_m": 0.0}),
    (4, {"correction_type": "prioritise_exit", "distance_delta_m": 0.0}),
]

for turn_idx, correction in corrections:
    print(f"   Turn {turn_idx} ({correction['correction_type']}):")
    engine._speak_focus_cue(turn_idx, correction)

# Test 5: Test feedback phrases
print("\n5. Feedback phrases:")
engine.previous_lap_turn_deltas = {1: 1.0, 2: 0.5, 3: 0.8}
engine.sector_results = [
    SectorResult(sector_idx=1, time=15.0, delta_to_target=0.7),  # improved
    SectorResult(sector_idx=2, time=12.5, delta_to_target=0.6),  # worse
    SectorResult(sector_idx=3, time=18.0, delta_to_target=0.8),  # same
]

for turn_idx in [1, 2, 3]:
    engine.focus_turns = [turn_idx]
    engine._give_focus_turn_feedback(turn_idx)

print("\n6. End-of-lap summary:")
engine.focus_turn_count = 1
engine.focus_turns = [1]
engine._give_focus_turn_summary()

engine.focus_turn_count = 3
engine.focus_turns = [1, 2, 3]
engine._give_focus_turn_summary()

print("\n" + "=" * 50)
print("Focus Turn Coaching System test complete!")