# Coaching constants

POLL_HZ = 20                    # Shared memory polling rate (Hz)
MIN_SPEED_MPS = 3.0             # Ignore below this (pit lane etc)
BRAKE_THRESHOLD = 8.0           # % brake pressure to detect braking zone start
MIN_ZONE_GAP_M = 150.0          # Merge braking zones closer than this
APPROACH_WARN_M = 400.0         # How far before brake point to give the cue
APPROACH_WINDOW_M = 50.0        # Window around the trigger point (don't repeat)
POST_CORNER_M = 100.0           # How far after exit to give feedback
SECTION_APPROACH_M = 300.0      # How far before section entry to fire section briefing
TTS_RATE = 175                  # Words per minute
TIER_PROMOTION_LAPS = 3         # Beat target N laps in a row to promote
INITIAL_TARGET_PCT = 0.92       # Start target = 92% of way from player to fastest
TIER_STEP_PCT = 0.15            # Each tier closes gap by 15%

# Strategic Lap Focus Model Constants
MAX_FOCUS_ENTITIES = 3          # Maximum number of entities to coach per lap
FOCUS_PERSISTENCE_THRESHOLD_S = 0.15  # Time loss threshold to keep entity in focus
MIN_SPACING_M = 600.0           # Minimum distance between selected entities
FOCUS_IMPROVEMENT_MARGIN_S = 0.10  # Margin for leaving top loss group
