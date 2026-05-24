#!/usr/bin/env python3
"""Опционально: создать mp4-заглушки в welcome/questions до сборки."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "in"

def main() -> None:
    try:
        import imageio.v3 as iio
        import numpy as np
    except ImportError:
        print("Установите: pip install imageio imageio-ffmpeg numpy")
        return

    for folder_name in ("00-welcome", "99-questions"):
        folder = IN / folder_name
        if not folder.is_dir():
            continue
        for i, color in enumerate([(28, 32, 48), (40, 56, 88), (56, 36, 64)]):
            target = folder / f"bg-loop-{i + 1}.mp4"
            if target.exists():
                continue
            base = np.full((360, 640, 3), color, dtype=np.uint8)
            frames = [
                np.clip(base * (0.8 + 0.2 * (t / 44)), 0, 255).astype(np.uint8)
                for t in range(45)
            ]
            iio.imwrite(target, frames, fps=15, codec="libx264")
            print("Создан", target)

if __name__ == "__main__":
    main()
