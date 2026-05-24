#!/usr/bin/env python3
"""Сборка HTML-презентации из каталога in/ в out/."""

from __future__ import annotations

import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import markdown
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent
IN_DIR = ROOT / "in"
OUT_DIR = ROOT / "out"
TEMPLATES_DIR = ROOT / "templates"

TALK_SECTIONS = ("проблема", "инструменты", "решение", "демо", "вопросы?")
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
DEMO_EXTS = IMAGE_EXTS | VIDEO_EXTS

MD_EXTENSIONS = [
    "markdown.extensions.extra",
    "markdown.extensions.nl2br",
    "markdown.extensions.sane_lists",
    "markdown.extensions.tables",
]


@dataclass
class Block:
    folder: Path
    order_key: str
    block_type: str  # welcome | talk | questions
    meta: dict = field(default_factory=dict)
    sections: dict[str, str] = field(default_factory=dict)
    raw_md: str = ""
    asset_prefix: str = ""


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return {}, text
    meta = yaml.safe_load(match.group(1)) or {}
    body = text[match.end() :]
    return meta, body


def split_sections(body: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current_key: str | None = None
    buffer: list[str] = []

    for line in body.splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line.strip())
        if heading:
            if current_key is not None:
                sections[current_key] = "\n".join(buffer).strip()
            current_key = heading.group(1).strip().lower()
            buffer = []
        else:
            buffer.append(line)

    if current_key is not None:
        sections[current_key] = "\n".join(buffer).strip()
    return sections


def md_to_html(text: str) -> str:
    if not text.strip():
        return ""
    return markdown.markdown(text, extensions=MD_EXTENSIONS)


def rewrite_asset_urls(html: str, asset_prefix: str) -> str:
    def repl(match: re.Match[str]) -> str:
        url = match.group(2)
        if url.startswith(("http://", "https://", "data:", "#")):
            return match.group(0)
        clean = url.lstrip("./")
        return f'{match.group(1)}{asset_prefix}/{clean}{match.group(3)}'

    return re.sub(r'(<img[^>]+src=")([^"]+)(")', repl, html)


def referenced_media(raw_md: str) -> set[str]:
    refs: set[str] = set()
    for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", raw_md):
        path = match.group(1).strip().split()[0]
        refs.add(Path(path).name.lower())
    return refs


def list_block_media(folder: Path, exclude_names: set[str]) -> list[Path]:
    files: list[Path] = []
    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        if path.name.lower() in exclude_names:
            continue
        if path.suffix.lower() not in DEMO_EXTS:
            continue
        if path.name.lower() == "slide.md":
            continue
        files.append(path)
    return files


def list_videos(folder: Path) -> list[Path]:
    return sorted(
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS
    )


def copy_asset(src: Path, dest_dir: Path) -> str:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    shutil.copy2(src, dest)
    rel = dest.relative_to(OUT_DIR).as_posix()
    return rel


def generate_placeholder_videos(dest_dir: Path, count: int = 3) -> list[Path]:
    """Создаёт короткие mp4-заглушки в out (не трогает in/)."""
    try:
        import imageio.v3 as iio
        import numpy as np
    except ImportError:
        return []

    dest_dir.mkdir(parents=True, exist_ok=True)
    palette = [
        (24, 24, 32),
        (32, 48, 72),
        (48, 32, 56),
    ]
    created: list[Path] = []
    for i in range(count):
        color = palette[i % len(palette)]
        base = np.full((368, 640, 3), color, dtype=np.uint8)
        seq = []
        for t in range(45):
            factor = 0.85 + 0.15 * ((t % 30) / 29)
            seq.append(np.clip(base * factor, 0, 255).astype(np.uint8))
        target = dest_dir / f"placeholder-{i + 1}.mp4"
        iio.imwrite(target, seq, fps=15, codec="libx264")
        created.append(target)
    return created


def load_block(folder: Path) -> Block:
    slide_path = folder / "slide.md"
    if not slide_path.exists():
        raise FileNotFoundError(f"Нет slide.md в {folder}")

    raw = slide_path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(raw)
    sections = split_sections(body)
    block_type = meta.get("type", "talk")
    order_key = folder.name

    return Block(
        folder=folder,
        order_key=order_key,
        block_type=block_type,
        meta=meta,
        sections=sections,
        raw_md=raw,
        asset_prefix=f"assets/{order_key}",
    )


def _block_steps(demo_count: int) -> list[dict[str, str]]:
    steps = [
        {"id": "проблема", "label": "Проблема"},
        {"id": "инструменты", "label": "Инструменты"},
        {"id": "решение", "label": "Решение"},
    ]
    for i in range(1, demo_count + 1):
        steps.append({"id": f"демо-{i}", "label": f"Демо {i}"})
    steps.append({"id": "вопросы?", "label": "Вопросы"})
    return steps


def build_slides(blocks: list[Block]) -> list[dict]:
    slides: list[dict] = []

    for block in blocks:
        asset_dir = OUT_DIR / "assets" / block.order_key
        title = block.meta.get("title", block.order_key)

        if block.block_type == "welcome":
            videos = list_videos(block.folder)
            if videos:
                video_urls = [copy_asset(v, asset_dir) for v in videos]
            else:
                placeholders = generate_placeholder_videos(asset_dir)
                video_urls = [p.relative_to(OUT_DIR).as_posix() for p in placeholders]
            slides.append(
                {
                    "type": "welcome",
                    "title": title,
                    "subtitle": block.meta.get("subtitle", ""),
                    "videos": video_urls,
                    "block_id": block.order_key,
                }
            )
            continue

        if block.block_type == "questions":
            videos = list_videos(block.folder)
            if videos:
                video_urls = [copy_asset(v, asset_dir) for v in videos]
            else:
                placeholders = generate_placeholder_videos(asset_dir)
                video_urls = [p.relative_to(OUT_DIR).as_posix() for p in placeholders]
            body_html = md_to_html(block.sections.get("текст", ""))
            body_html = rewrite_asset_urls(body_html, block.asset_prefix)
            slides.append(
                {
                    "type": "questions",
                    "title": title,
                    "subtitle": block.meta.get("subtitle", ""),
                    "html": body_html,
                    "videos": video_urls,
                    "block_id": block.order_key,
                }
            )
            continue

        # talk block
        author = block.meta.get("author", "")
        refs = referenced_media(block.raw_md)

        demo_files_preview = [
            p
            for p in list_block_media(block.folder, exclude_names={"slide.md"})
            if p.name.lower() not in refs and p.suffix.lower() in DEMO_EXTS
        ]
        demo_files_preview.sort(
            key=lambda p: (0 if p.name.lower().startswith("demo-") else 1, p.name.lower())
        )
        block_steps = _block_steps(len(demo_files_preview))
        talk_meta = {
            "block_title": title,
            "author": author,
            "block_steps": block_steps,
        }

        for key in ("проблема", "инструменты", "решение", "вопросы?"):
            section_title = key.capitalize() if key != "вопросы?" else "Вопросы?"
            content = block.sections.get(key, "")
            if key == "вопросы?":
                section_title = "Вопросы?"
            html = md_to_html(content)
            html = rewrite_asset_urls(html, block.asset_prefix)
            slides.append(
                {
                    "type": "section",
                    "block_id": block.order_key,
                    "section": key,
                    "section_title": section_title,
                    "step_id": key,
                    "html": html,
                    **talk_meta,
                }
            )

        # копируем схемы и прочие файлы из MD
        for name in refs:
            src = block.folder / name
            if src.exists():
                copy_asset(src, asset_dir)

        demo_intro = block.sections.get("демо", "")
        demo_intro_html = rewrite_asset_urls(
            md_to_html(demo_intro), block.asset_prefix
        )

        demo_files = [
            p
            for p in list_block_media(block.folder, exclude_names={"slide.md"})
            if p.name.lower() not in refs and p.suffix.lower() in DEMO_EXTS
        ]
        # приоритет файлам с префиксом demo-
        demo_files.sort(
            key=lambda p: (0 if p.name.lower().startswith("demo-") else 1, p.name.lower())
        )

        total_demo = len(demo_files)
        for idx, media in enumerate(demo_files, start=1):
            rel = copy_asset(media, asset_dir)
            mime = "video" if media.suffix.lower() in VIDEO_EXTS else "image"
            slides.append(
                {
                    "type": "demo",
                    "block_id": block.order_key,
                    "src": rel,
                    "mime": mime,
                    "index": idx,
                    "total": total_demo,
                    "step_id": f"демо-{idx}",
                    "intro_html": demo_intro_html if idx == 1 else "",
                    **talk_meta,
                }
            )

        if total_demo == 0 and demo_intro_html:
            slides.append(
                {
                    "type": "demo",
                    "block_id": block.order_key,
                    "src": "",
                    "mime": "text",
                    "index": 1,
                    "total": 1,
                    "step_id": "демо-1",
                    "intro_html": demo_intro_html,
                    **talk_meta,
                }
            )

    return slides


def clean_out() -> None:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)


def copy_to_docs() -> None:
    """Копия собранного сайта в docs/ для GitHub Pages."""
    docs = ROOT / "docs"
    if docs.exists():
        shutil.rmtree(docs)
    shutil.copytree(OUT_DIR, docs)


def render_index(slides: list[dict], meta: dict) -> None:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("presentation.html.j2")
    html = template.render(
        slides_json=json.dumps(slides, ensure_ascii=False),
        presentation_title=meta.get("presentation_title", "Выступление"),
    )
    (OUT_DIR / "index.html").write_text(html, encoding="utf-8")


def collect_blocks() -> list[Block]:
    if not IN_DIR.exists():
        raise FileNotFoundError(f"Каталог {IN_DIR} не найден")

    folders = sorted(
        p for p in IN_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")
    )
    if not folders:
        raise FileNotFoundError(f"В {IN_DIR} нет папок блоков")

    return [load_block(folder) for folder in folders]


def main() -> int:
    print("Сборка презентации...")
    blocks = collect_blocks()
    clean_out()

    slides = build_slides(blocks)
    presentation_title = blocks[0].meta.get("title", "Выступление") if blocks else "Выступление"
    render_index(slides, {"presentation_title": presentation_title})
    copy_to_docs()

    print(f"Готово: {OUT_DIR / 'index.html'}")
    print(f"GitHub Pages: {ROOT / 'docs' / 'index.html'}")
    print(f"Слайдов: {len(slides)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
