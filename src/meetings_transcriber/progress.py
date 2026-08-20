from __future__ import annotations

import re
from dataclasses import dataclass

TIMESTAMP_RE = re.compile(
    r"Transcript:\s*\[(?P<start>\d+(?:\.\d+)?)\s*-->\s*(?P<end>\d+(?:\.\d+)?)\]"
)


def format_clock(seconds: float) -> str:
    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


@dataclass(frozen=True)
class Progress:
    current: float
    total: float

    @property
    def percent(self) -> float:
        return min(100.0, max(0.0, self.current / self.total * 100.0))

    def render(self) -> str:
        return f"[{self.percent:6.2f}%] {format_clock(self.current)} / {format_clock(self.total)}"


def parse_progress(line: str, total: float) -> Progress | None:
    match = TIMESTAMP_RE.search(line)
    if not match or total <= 0:
        return None
    return Progress(current=float(match.group("end")), total=total)
