from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class ProgressTracker:
    total: int
    description: str
    position: int = 0
    leave: bool = True

    def __post_init__(self) -> None:
        self.current = 0
        self._bar: Any | None = None
        self._tqdm: Any | None = None
        try:
            from tqdm import tqdm

            self._tqdm = tqdm
            self._bar = tqdm(
                total=self.total,
                desc=self.description,
                unit="step",
                position=self.position,
                leave=self.leave,
                dynamic_ncols=True,
            )
        except ImportError:
            self.write(f"{self.description}: 0/{self.total}")

    def update(self, step: str, advance: int = 1) -> None:
        self.current += advance
        if self._bar is not None:
            self._bar.set_description_str(step)
            self._bar.update(advance)
        else:
            self.write(f"{step}: {min(self.current, self.total)}/{self.total}")

    def child(self, total: int, description: str, leave: bool = False) -> ProgressTracker:
        return ProgressTracker(
            total=total,
            description=description,
            position=self.position + 1,
            leave=leave,
        )

    def write(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        text = f"[{timestamp}] {message}"
        if self._tqdm is not None:
            self._tqdm.write(text)
        else:
            print(text, flush=True)

    def close(self) -> None:
        if self._bar is not None:
            self._bar.close()


class NullProgress:
    def write(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}", flush=True)

    def update(self, step: str, advance: int = 1) -> None:
        self.write(step)

    def child(self, total: int, description: str, leave: bool = False) -> ProgressTracker:
        return ProgressTracker(total=total, description=description, leave=leave)

    def close(self) -> None:
        return None
