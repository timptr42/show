#!/usr/bin/env python3
"""Демо-файлы в блоках выступления: копия видео из welcome + тестовые картинки (welcome не трогаем)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "in"
WELCOME = IN / "00-welcome"

# 10 проектов, демо 1–3 слайда (цикл 3,2,1)
BLOCKS = (
    ("01-monitoring-alerts", "Мониторинг и алерты", 3),
    ("02-cursor-workflow", "Cursor как рабочий процесс", 2),
    ("03-git-organization", "Организация репозиториев CPL", 1),
    ("04-telegram-bots", "Telegram-боты для команды", 3),
    ("05-api-gateway", "API Gateway и контракты", 2),
    ("06-ci-pipeline", "CI-пайплайн за вечер", 1),
    ("07-observability", "Наблюдаемость сервисов", 3),
    ("08-security-scan", "Безопасность в CI", 2),
    ("09-docs-portal", "Портал документации", 1),
    ("10-team-onboarding", "Онбординг команды", 3),
)


def list_welcome_videos() -> list[Path]:
    exts = {".mp4", ".webm", ".mov", ".m4v"}
    if not WELCOME.is_dir():
        return []
    return sorted(
        p for p in WELCOME.iterdir() if p.is_file() and p.suffix.lower() in exts
    )


def make_demo_svg(path: Path, label: str, project: str) -> None:
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720">
  <rect width="1280" height="720" fill="#f6f6f4"/>
  <rect x="40" y="40" width="1200" height="640" rx="8" fill="#fff" stroke="#111" stroke-width="3"/>
  <text x="640" y="320" text-anchor="middle" font-family="Segoe UI, sans-serif" font-size="56" font-weight="800" fill="#111">{label}</text>
  <text x="640" y="400" text-anchor="middle" font-family="Segoe UI, sans-serif" font-size="28" fill="#4a4a4a">{project}</text>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def clear_old_demos(folder: Path) -> None:
    """Удаляет только demo-* в папке блока, welcome не трогаем."""
    for p in folder.glob("demo-*"):
        if p.is_file():
            p.unlink()


def seed_block(folder: Path, project: str, count: int, videos: list[Path], video_idx: int) -> int:
    clear_old_demos(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(1, count + 1):
        use_video = i % 2 == 0 and video_idx < len(videos)
        if use_video:
            ext = videos[video_idx].suffix.lower()
            dest = folder / f"demo-{i:02d}{ext}"
            shutil.copy2(videos[video_idx], dest)
            video_idx += 1
            print(f"  {dest.relative_to(ROOT)}  <-  copy video")
        else:
            dest = folder / f"demo-{i:02d}.svg"
            make_demo_svg(dest, f"Тестовое демо {i}", project)
            print(f"  {dest.relative_to(ROOT)}  (svg)")
    return video_idx


def main() -> int:
    videos = list_welcome_videos()
    if not videos:
        print("Нет видео в in/00-welcome/", file=sys.stderr)
        return 1

    print(f"Видео в welcome: {len(videos)} (копии, исходники остаются)")
    vid_i = 0
    for block_id, title, count in BLOCKS:
        folder = IN / block_id
        print(f"\n{block_id} ({count} демо):")
        vid_i = seed_block(folder, title, count, videos, vid_i)

    print("\nГотово.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
