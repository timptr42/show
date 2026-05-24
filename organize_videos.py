#!/usr/bin/env python3
"""
Раскладка видео:
  - по 2 в каждый блок выступления (demo-01, demo-02)
  - остальные — в 00-welcome и 99-questions (bg-01, bg-02, …)

Ищет исходники в in/00-welcome и в Downloads (kling_*.mp4).
Копирует внешние файлы, внутри in/ — перемещает.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IN = ROOT / "in"
DOWNLOADS = Path.home() / "Downloads"

TALK_BLOCKS = (
    "01-monitoring-alerts",
    "02-cursor-workflow",
    "03-git-organization",
)
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v"}
MIN_BYTES = 50_000


def is_real_video(path: Path) -> bool:
    return (
        path.is_file()
        and path.suffix.lower() in VIDEO_EXTS
        and path.stat().st_size >= MIN_BYTES
    )


def collect_sources() -> list[Path]:
    candidates: list[Path] = []

    welcome = IN / "00-welcome"
    if welcome.is_dir():
        candidates.extend(p for p in welcome.iterdir() if is_real_video(p))

    if DOWNLOADS.is_dir():
        candidates.extend(
            p for p in DOWNLOADS.glob("kling_*.mp4") if is_real_video(p)
        )

    # уже разложенные демо — вернуть в пул
    for block in TALK_BLOCKS:
        folder = IN / block
        if folder.is_dir():
            candidates.extend(p for p in folder.glob("demo-*.mp4") if is_real_video(p))
            candidates.extend(p for p in folder.glob("demo-*.webm") if is_real_video(p))

    for folder in (IN / "99-questions",):
        if folder.is_dir():
            candidates.extend(p for p in folder.glob("bg-*.mp4") if is_real_video(p))

    # уникальность по размеру (один файл — одна копия)
    by_size: dict[int, Path] = {}
    for p in sorted(candidates, key=lambda x: x.name.lower()):
        size = p.stat().st_size
        if size not in by_size:
            by_size[size] = p

    return sorted(by_size.values(), key=lambda p: p.name.lower())


def safe_unlink(path: Path) -> None:
    if path.exists():
        path.unlink()


def clear_targets() -> None:
    for folder in (IN / "00-welcome", IN / "99-questions", *(IN / b for b in TALK_BLOCKS)):
        if not folder.is_dir():
            continue
        for pattern in ("placeholder-*.mp4", "bg-*.mp4", "bg-*.webm", "demo-*.mp4", "demo-*.webm"):
            for p in folder.glob(pattern):
                safe_unlink(p)
        for p in folder.glob("demo-*.svg"):
            safe_unlink(p)


def place(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        safe_unlink(dest)
    try:
        if src.resolve().parent == dest.resolve().parent:
            src.rename(dest)
            return
    except OSError:
        pass
    try:
        src.rename(dest)
    except OSError:
        shutil.copy2(src, dest)


def main() -> int:
    clear_targets()
    sources = collect_sources()
    if not sources:
        print("Нет видео: положите файлы в in/00-welcome или Downloads/kling_*.mp4", file=sys.stderr)
        return 1

    need_talk = 2 * len(TALK_BLOCKS)
    if len(sources) < need_talk:
        print(f"Мало видео: {len(sources)}, нужно минимум {need_talk}.", file=sys.stderr)
        return 1

    idx = 0
    for block in TALK_BLOCKS:
        folder = IN / block
        for n in (1, 2):
            ext = sources[idx].suffix.lower()
            dest = folder / f"demo-{n:02d}{ext}"
            place(sources[idx], dest)
            print(dest.relative_to(ROOT))
            idx += 1

    rest = sources[idx:]
    half = (len(rest) + 1) // 2
    for i, src in enumerate(rest[:half], start=1):
        dest = IN / "00-welcome" / f"bg-{i:02d}{src.suffix.lower()}"
        place(src, dest)
        print(dest.relative_to(ROOT))

    for i, src in enumerate(rest[half:], start=1):
        dest = IN / "99-questions" / f"bg-{i:02d}{src.suffix.lower()}"
        place(src, dest)
        print(dest.relative_to(ROOT))

    print(f"\nИтого: {len(sources)} -> 6 демо + {half} welcome + {len(rest) - half} Q/A")
    return 0


if __name__ == "__main__":
    sys.exit(main())
