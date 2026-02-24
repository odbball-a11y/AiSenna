# -*- coding: utf-8 -*-
"""
Race Engineer Speech Generation Layer
======================================
Minimal, professional pit-wall radio style.
Instruction mode (pre-corner) and Assessment mode (post-corner) are separate.

Design rules:
  - Pre-corner: Corner. Fault. Fix.  Max 8 words total.
  - Post-corner: Classification-based. No corner number. Max 8 words.
  - Trend detection over last 3 laps per corner+issue.
  - No delta numbers in pre-corner. Gap hint optional in post.
  - No motivational fluff. No explanations.
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Dict, Optional

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

MAX_WORDS = 8  # hard cap on all generated phrases

# Classification thresholds per issue type.
# Keys: strong, small, noise, achieved  (all in the issue's natural unit)
ISSUE_THRESHOLDS: Dict[str, Dict[str, float]] = {
    'brake_early':        {'strong': 15,  'small': 5,   'noise': 2,   'achieved': 5  },
    'apex_slow':          {'strong': 6,   'small': 2,   'noise': 1,   'achieved': 3  },
    'exit_slow':          {'strong': 6,   'small': 2,   'noise': 1,   'achieved': 3  },
    'apex_early':         {'strong': 15,  'small': 8,   'noise': 3,   'achieved': 8  },
    'line_wide':          {'strong': 1.0, 'small': 0.3, 'noise': 0.1, 'achieved': 0.3},
    'no_trail_brake':     {'strong': 5,   'small': 2,   'noise': 1,   'achieved': 5  },
    'complex_min_speed':  {'strong': 10,  'small': 4,   'noise': 2,   'achieved': 5  },
    'complex_exit_speed': {'strong': 10,  'small': 4,   'noise': 2,   'achieved': 5  },
    'brake_stab':         {'strong': 5,   'small': 2,   'noise': 1,   'achieved': 3  },
    # Section-level time delta (seconds) — used by generate_section_assessment
    'section_time':       {'strong': 0.5, 'small': 0.2, 'noise': 0.1, 'achieved': 0.2},
}

_DEFAULT_THRESHOLDS = {'strong': 10, 'small': 4, 'noise': 2, 'achieved': 5}

# Unit suffix for {gap} formatting in assessment phrases.
# Issues not listed here default to no suffix (raw number).
_ISSUE_UNITS: Dict[str, str] = {
    'brake_early':    'm',
    'apex_early':     'm',
    'line_wide':      'm',
    'apex_slow':      'kph',
    'exit_slow':      'kph',
    'no_trail_brake': 'kph',
    'complex_min_speed':  'kph',
    'complex_exit_speed': 'kph',
}

# ─────────────────────────────────────────────────────────────────────────────
# Phrase libraries
# ─────────────────────────────────────────────────────────────────────────────

# Pre-corner instruction phrases.
# Format tokens: {idx} = corner number, {name} = complex name (if applicable)
ISSUE_INSTRUCTIONS: Dict[str, list] = {
    'brake_early':        ["T{idx}. Brake deeper.",       "T{idx}. Go deeper."           ],
    'apex_slow':          ["T{idx}. Carry speed.",         "T{idx}. More momentum."       ],
    'exit_slow':          ["T{idx}. Earlier throttle.",    "T{idx}. Power sooner."        ],
    'apex_early':         ["T{idx}. Later apex.",          "T{idx}. Hold the entry."      ],
    'line_wide':          ["T{idx}. Clip the inside.",     "T{idx}. Use the kerb."        ],
    'no_trail_brake':     ["T{idx}. Trail the brake.",     "T{idx}. Release later."       ],
    'brake_stab':         ["T{idx}. Smooth the brake.",    "T{idx}. Settle the pedal."    ],
    'complex_min_speed':  ["{name}. Flow through.",        "{name}. Carry more."          ],
    'complex_exit_speed': ["{name}. Exit with power.",     "{name}. Throttle sooner."     ],
}

# Post-corner assessment phrases.
# Classification buckets: no_change | small | strong | achieved | regression | overshoot
# Format tokens: {gap} = remaining gap with unit suffix (small bucket only)
ASSESSMENT_PHRASES: Dict[str, list] = {
    'no_change':  ["No change.",         "Still early.",      "Same again."      ],
    'small':      ["Better. {gap} more.", "Good step. More.", "Closer."          ],
    'strong':     ["Good. Nearly there.", "That's better.",   "Big step."        ],
    'achieved':   ["That's it.",          "Good correction.", "Hold that."       ],
    'regression': ["Lost ground.",        "Went backwards.",  "That slipped."    ],
    'overshoot':  ["Too far.",            "Bring it back.",   "Overdone."        ],
}

# Trend reinforcement phrases — replace generic assessment when trend detected.
TREND_PHRASES: Dict[str, list] = {
    'trend_2': ["Improving each lap.", "Building.", "Keep that trend.", "Confidence growing."],
    'trend_3': ["That's consistent.",  "Keep building."                                     ],
}

# Positive buckets used for trend detection
_POSITIVE_BUCKETS = {'small', 'strong', 'achieved'}

# ─────────────────────────────────────────────────────────────────────────────
# Section-level phrase libraries
# ─────────────────────────────────────────────────────────────────────────────

# Section briefing phrases — keyed by Complex.complex_type
# Format token: {name} = section display name
SECTION_INSTRUCTIONS: Dict[str, list] = {
    'flow_zone':   ["{name}. Flow through.",    "{name}. Commit early.",       "{name}. Carry momentum." ],
    'esses':       ["{name}. Flow through.",    "{name}. Link the apexes.",    "{name}. Keep the rhythm."],
    'chicane':     ["{name}. Hit both apexes.", "{name}. Straight line through."                         ],
    'double_apex': ["{name}. Link them up.",    "{name}. Carry to the second."                           ],
    'linked':      ["{name}. Momentum first.",  "{name}. Build through."                                 ],
    'default':     ["{name}. Focus.",           "{name}. Smooth through."                                ],
}

# Bottleneck hint — fires when a specific corner is the biggest speed deficit
# Format tokens: {name} = section name, {corner} = corner number
SECTION_BOTTLENECK_PHRASES: list = [
    "{name}. T{corner}. Carry more.",
    "{name}. T{corner}. Don't back off.",
]

# Post-section assessment phrases — same 6-bucket schema, time-based
# Format token: {gap} = time gap formatted as seconds (small bucket only)
SECTION_ASSESSMENT_PHRASES: Dict[str, list] = {
    'no_change':  ["Same time.",       "No change.",      "Hold there."     ],
    'small':      ["Better. {gap}.",   "Good step.",      "Closer."         ],
    'strong':     ["Good run.",        "Big step.",       "That's progress."],
    'achieved':   ["On pace.",         "That's it.",      "Match held."     ],
    'regression': ["Slower.",          "Lost time.",      "That slipped."   ],
    'overshoot':  ["Under target.",    "Ahead of pace.",  "Easy."           ],
}


# ─────────────────────────────────────────────────────────────────────────────
# RaceEngineerCoach
# ─────────────────────────────────────────────────────────────────────────────

class RaceEngineerCoach:
    """
    Minimal, professional race engineer speech generation.

    Corner modes:
      generate_instruction()         — pre-corner, directional instruction
      generate_assessment()          — post-corner, behavioural evaluation with trend

    Section modes:
      generate_section_instruction() — pre-section briefing (one thought before the complex)
      generate_section_assessment()  — post-section verdict (time-based, 6-bucket)
    """

    def __init__(self):
        # Rotation state: maps any phrase-list key → next index to use
        self._instr_idx:  Dict[str, int] = {}
        self._assess_idx: Dict[str, int] = {}
        self._trend_idx:  Dict[str, int] = {}

        # Section rotation state
        self._section_instr_idx:  Dict[str, int] = {}
        self._section_assess_idx: Dict[str, int] = {}

        # Per-corner, per-issue classification history (last 3 laps)
        # Key format: "C{corner_idx}_{issue_type}"
        # Section history uses key format: "S{complex_idx}"
        self._delta_history: Dict[str, deque] = {}

    # ─────────────────────────────────────────────
    # Public: Instruction mode (pre-corner)
    # ─────────────────────────────────────────────

    def generate_instruction(self, corner_idx: int, issue_type: str,
                             complex_name: str = "") -> str:
        """
        Generate a short pre-corner instruction.
        Format: "T{idx}. Fix."  Max MAX_WORDS words.
        """
        phrases = ISSUE_INSTRUCTIONS.get(issue_type)
        if not phrases:
            log.debug("generate_instruction: no phrases for issue_type=%s", issue_type)
            return ""

        phrase = self._rotate(self._instr_idx, issue_type, phrases)

        try:
            text = phrase.format(idx=corner_idx, name=complex_name or "")
        except KeyError:
            text = phrase

        text = self._enforce_word_limit(text)
        log.debug("INSTRUCTION C%d [%s]: %s", corner_idx, issue_type, text)
        return text

    # ─────────────────────────────────────────────
    # Public: Assessment mode (post-corner)
    # ─────────────────────────────────────────────

    def generate_assessment(self, corner_idx: int, issue_type: str,
                            improvement: float, remaining: float) -> str:
        """
        Generate post-corner behavioural assessment.

        Args:
            corner_idx:  Corner number
            issue_type:  Issue key (e.g. 'brake_early', 'apex_slow')
            improvement: Delta vs previous lap — positive = better this lap
            remaining:   Gap to target — positive = still needs work, negative = overshot
        """
        bucket = self._classify(issue_type, improvement, remaining)

        # Record and check trend before choosing phrase
        hist_key = f"C{corner_idx}_{issue_type}"
        if hist_key not in self._delta_history:
            self._delta_history[hist_key] = deque(maxlen=3)
        self._delta_history[hist_key].append(bucket)

        # Trend overrides generic assessment
        trend_key = self._get_trend(corner_idx, issue_type)
        if trend_key:
            text = self._rotate(self._trend_idx, trend_key, TREND_PHRASES[trend_key])
            text = self._enforce_word_limit(text)
            log.debug("ASSESSMENT C%d [%s] → TREND %s: %s", corner_idx, issue_type, trend_key, text)
            return text

        phrases = ASSESSMENT_PHRASES.get(bucket)
        if not phrases:
            return ""

        phrase = self._rotate(self._assess_idx, bucket, phrases)

        # Format {gap} if present — only used in 'small' bucket
        gap_str = self._format_gap(issue_type, remaining)
        try:
            text = phrase.format(gap=gap_str)
        except KeyError:
            text = phrase

        text = self._enforce_word_limit(text)
        log.debug("ASSESSMENT C%d [%s] → %s: %s", corner_idx, issue_type, bucket, text)
        return text

    # ─────────────────────────────────────────────
    # Public: Section mode (pre-section briefing)
    # ─────────────────────────────────────────────

    def generate_section_instruction(self, complex_idx: int, complex_type: str,
                                     complex_name: str = "",
                                     bottleneck_corner_idx: int = 0) -> str:
        """
        Generate a pre-section briefing phrase.

        If a bottleneck corner is known (biggest speed gap), use the bottleneck
        phrase to focus the driver on that specific point.  Otherwise fall back
        to a generic complex-type phrase.

        Args:
            complex_idx:           Complex index (used for rotation key only)
            complex_type:          e.g. 'flow_zone', 'esses', 'chicane', etc.
            complex_name:          Display name (e.g. "Maggots-Becketts")
            bottleneck_corner_idx: Corner with the biggest speed deficit (0 = unknown)
        """
        display = complex_name or complex_type

        if bottleneck_corner_idx > 0:
            key = "section_bottleneck"
            phrase = self._rotate(self._section_instr_idx, key, SECTION_BOTTLENECK_PHRASES)
            try:
                text = phrase.format(name=display, corner=bottleneck_corner_idx)
            except KeyError:
                text = phrase
            text = self._enforce_word_limit(text)
            log.debug("SECTION INSTRUCTION [%s] bottleneck=T%d: %s",
                      display, bottleneck_corner_idx, text)
            return text

        phrases = SECTION_INSTRUCTIONS.get(complex_type, SECTION_INSTRUCTIONS['default'])
        key = f"section_{complex_type}"
        phrase = self._rotate(self._section_instr_idx, key, phrases)
        try:
            text = phrase.format(name=display)
        except KeyError:
            text = phrase
        text = self._enforce_word_limit(text)
        log.debug("SECTION INSTRUCTION [%s] type=%s: %s", display, complex_type, text)
        return text

    # ─────────────────────────────────────────────
    # Public: Section mode (post-section assessment)
    # ─────────────────────────────────────────────

    def generate_section_assessment(self, complex_idx: int,
                                    improvement: float, remaining: float) -> str:
        """
        Generate a post-section time-based assessment.

        Args:
            complex_idx: Complex index (for history key and rotation)
            improvement: prev_section_time - this_section_time  (positive = faster)
            remaining:   this_section_time - personal_best_time (positive = off best)
        """
        bucket = self._classify('section_time', improvement, remaining)

        hist_key = f"S{complex_idx}"
        if hist_key not in self._delta_history:
            self._delta_history[hist_key] = deque(maxlen=3)
        self._delta_history[hist_key].append(bucket)

        # Trend check using raw history key
        trend_key = self._get_trend_by_key(hist_key)
        if trend_key:
            text = self._rotate(self._trend_idx, trend_key, TREND_PHRASES[trend_key])
            text = self._enforce_word_limit(text)
            log.debug("SECTION ASSESSMENT S%d → TREND %s: %s", complex_idx, trend_key, text)
            return text

        phrases = SECTION_ASSESSMENT_PHRASES.get(bucket, [])
        if not phrases:
            return ""

        phrase = self._rotate(self._section_assess_idx, bucket, phrases)

        # Format {gap} as seconds (only the 'small' bucket uses it)
        gap_str = f"{abs(remaining):.1f}s"
        try:
            text = phrase.format(gap=gap_str)
        except KeyError:
            text = phrase

        text = self._enforce_word_limit(text)
        log.debug("SECTION ASSESSMENT S%d → %s: %s", complex_idx, bucket, text)
        return text

    # ─────────────────────────────────────────────
    # Classification
    # ─────────────────────────────────────────────

    def _classify(self, issue_type: str, improvement: float, remaining: float) -> str:
        """
        Classify driver performance into one of six buckets.

        Priority order:
          overshoot > achieved > strong > small > no_change > regression
        """
        t = ISSUE_THRESHOLDS.get(issue_type, _DEFAULT_THRESHOLDS)

        # Overshot: went past target by more than the achieved threshold
        if remaining < -t['achieved']:
            return 'overshoot'

        # Achieved: within achieved threshold of target
        if remaining <= t['achieved']:
            return 'achieved'

        # Positive improvements
        if improvement >= t['strong']:
            return 'strong'
        if improvement >= t['small']:
            return 'small'

        # Noise band — treat as no change
        if improvement > -t['noise']:
            return 'no_change'

        # Clear regression
        return 'regression'

    # ─────────────────────────────────────────────
    # Trend detection
    # ─────────────────────────────────────────────

    def _get_trend(self, corner_idx: int, issue_type: str) -> Optional[str]:
        """
        Check last 3 laps for consecutive positive improvement.
        Returns 'trend_3', 'trend_2', or None.
        Only triggered AFTER recording the latest classification.
        """
        hist_key = f"C{corner_idx}_{issue_type}"
        history = self._delta_history.get(hist_key)
        if not history:
            return None

        buckets = list(history)  # oldest first, len 1-3

        # Need at least 2 entries
        if len(buckets) < 2:
            return None

        # Last 3 consecutive positive
        if len(buckets) >= 3 and all(b in _POSITIVE_BUCKETS for b in buckets[-3:]):
            return 'trend_3'

        # Last 2 consecutive positive
        if all(b in _POSITIVE_BUCKETS for b in buckets[-2:]):
            return 'trend_2'

        return None

    def _get_trend_by_key(self, hist_key: str) -> Optional[str]:
        """
        Check trend by raw history key (e.g. 'S{complex_idx}').
        Identical logic to _get_trend() but takes the key directly.
        """
        history = self._delta_history.get(hist_key)
        if not history:
            return None

        buckets = list(history)

        if len(buckets) < 2:
            return None

        if len(buckets) >= 3 and all(b in _POSITIVE_BUCKETS for b in buckets[-3:]):
            return 'trend_3'

        if all(b in _POSITIVE_BUCKETS for b in buckets[-2:]):
            return 'trend_2'

        return None

    # ─────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────

    @staticmethod
    def _rotate(idx_dict: Dict[str, int], key: str, phrase_list: list) -> str:
        """Round-robin rotate through a phrase list."""
        current = idx_dict.get(key, -1)
        next_idx = (current + 1) % len(phrase_list)
        idx_dict[key] = next_idx
        return phrase_list[next_idx]

    @staticmethod
    def _format_gap(issue_type: str, remaining: float) -> str:
        """Format remaining gap with appropriate unit for {gap} token."""
        unit = _ISSUE_UNITS.get(issue_type, '')
        value = abs(remaining)
        if unit == 'm':
            return f"{value:.0f}m"
        elif unit == 'kph':
            return f"{value:.0f}kph"
        else:
            return f"{value:.0f}"

    @staticmethod
    def _enforce_word_limit(text: str) -> str:
        """Hard-cap output at MAX_WORDS words."""
        words = text.split()
        if len(words) > MAX_WORDS:
            truncated = ' '.join(words[:MAX_WORDS])
            log.warning("Phrase truncated to %d words: '%s' → '%s'",
                        MAX_WORDS, text, truncated)
            return truncated
        return text
