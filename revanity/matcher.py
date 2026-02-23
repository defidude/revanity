"""Pattern matching strategies for vanity address search."""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MatchMode(Enum):
    PREFIX = "prefix"
    SUFFIX = "suffix"
    CONTAINS = "contains"
    REGEX = "regex"


@dataclass(frozen=True)
class MatchPattern:
    """Immutable, picklable pattern specification for workers.

    Note: compiled regex is not pickled. Workers must call compile() after
    receiving the pattern (re.Pattern is not picklable across processes).
    """
    mode: MatchMode
    pattern: str
    case_sensitive: bool = False

    def compile(self) -> "CompiledPattern":
        """Return a CompiledPattern ready for fast matching in a worker."""
        if self.mode == MatchMode.REGEX:
            flags = 0 if self.case_sensitive else re.IGNORECASE
            return CompiledPattern(self.mode, self.pattern, re.compile(self.pattern, flags))
        return CompiledPattern(self.mode, self.pattern, None)


class CompiledPattern:
    """Worker-local compiled pattern for fast matching."""

    __slots__ = ("mode", "pattern", "_regex")

    def __init__(self, mode: MatchMode, pattern: str, regex: Optional[re.Pattern]):
        self.mode = mode
        self.pattern = pattern
        self._regex = regex

    def matches(self, hex_addr: str) -> bool:
        """Test if a 32-char lowercase hex address matches this pattern."""
        if self.mode == MatchMode.PREFIX:
            return hex_addr.startswith(self.pattern)
        elif self.mode == MatchMode.SUFFIX:
            return hex_addr.endswith(self.pattern)
        elif self.mode == MatchMode.CONTAINS:
            return self.pattern in hex_addr
        elif self.mode == MatchMode.REGEX:
            return bool(self._regex.search(hex_addr))
        return False


def validate_hex_pattern(pattern: str) -> str:
    """Validate a pattern contains only valid hex characters.

    Returns the lowercased pattern.
    Raises ValueError for invalid patterns.
    """
    cleaned = pattern.lower().strip()
    if not cleaned:
        raise ValueError("Pattern cannot be empty.")
    if not all(c in "0123456789abcdef" for c in cleaned):
        raise ValueError(
            f"Pattern '{pattern}' contains non-hex characters. "
            "Only 0-9 and a-f are valid."
        )
    if len(cleaned) > 32:
        raise ValueError(
            f"Pattern length {len(cleaned)} exceeds maximum address length of 32 hex chars."
        )
    return cleaned


def estimate_difficulty(pattern: MatchPattern) -> dict:
    """Estimate expected attempts and time to find a match.

    Returns dict with: expected_attempts, estimated_seconds_per_core, difficulty_description
    """
    if pattern.mode == MatchMode.PREFIX:
        expected = 16 ** len(pattern.pattern)
    elif pattern.mode == MatchMode.SUFFIX:
        expected = 16 ** len(pattern.pattern)
    elif pattern.mode == MatchMode.CONTAINS:
        n = len(pattern.pattern)
        positions = max(1, 32 - n + 1)
        expected = (16 ** n) / positions
    elif pattern.mode == MatchMode.REGEX:
        return {
            "expected_attempts": None,
            "estimated_seconds_per_core": None,
            "difficulty_description": "Cannot estimate for regex",
        }
    else:
        expected = -1

    keys_per_sec = 5000  # conservative single-core estimate
    secs = expected / keys_per_sec if expected > 0 else None

    if expected < 100:
        desc = "Instant"
    elif expected < 100_000:
        desc = "Seconds"
    elif expected < 10_000_000:
        desc = "Minutes"
    elif expected < 1_000_000_000:
        desc = "Hours"
    elif expected < 100_000_000_000:
        desc = "Days"
    else:
        desc = "Weeks+ (consider a shorter pattern)"

    return {
        "expected_attempts": int(expected),
        "estimated_seconds_per_core": secs,
        "difficulty_description": desc,
    }
