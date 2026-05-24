#!/usr/bin/env python3
"""Сборка HTML-презентации из каталога in/ в out/."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import markdown
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent
IN_DIR = ROOT / "in"
OUT_DIR = ROOT / "out"
TEMPLATES_DIR = ROOT / "templates"

VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
DEMO_EXTS = IMAGE_EXTS | VIDEO_EXTS

MD_EXTENSIONS = [
    "markdown.extensions.extra",
    "markdown.extensions.nl2br",
    "markdown.extensions.sane_lists",
    "markdown.extensions.tables",
]

_ANSI = {
    "reset": "\033[0m",
    "dim": "\033[2m",
    "bold": "\033[1m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "cyan": "\033[36m",
    "red": "\033[31m",
}


class BuildLog:
    """Красивый текстовый лог в консоль."""

    def __init__(self) -> None:
        self._use_color = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
        self._t0 = time.perf_counter()
        self._warnings = 0
        self.assets_copied = 0

    def _c(self, code: str, text: str) -> str:
        if not self._use_color:
            return text
        return f"{_ANSI.get(code, '')}{text}{_ANSI['reset']}"

    def _out(self, line: str = "") -> None:
        print(line, flush=True)

    def banner(self) -> None:
        self._out()
        self._out(self._c("cyan", "  +---------------------------------------------------+"))
        self._out(
            self._c("cyan", "  |")
            + self._c("bold", "          СБОРКА HTML-ПРЕЗЕНТАЦИИ                 ")
            + self._c("cyan", "|")
        )
        self._out(self._c("cyan", "  +---------------------------------------------------+"))
        self._out(self._c("dim", f"  {ROOT}"))
        self._out()

    def phase(self, title: str) -> None:
        self._out(self._c("bold", f"  >> {title}"))
        self._out(self._c("dim", "  " + "-" * 52))

    def ok(self, msg: str, indent: int = 2) -> None:
        pad = " " * indent
        self._out(f"{pad}{self._c('green', '[ok]')} {msg}")

    def item(self, msg: str, indent: int = 4) -> None:
        pad = " " * indent
        self._out(f"{pad}{self._c('dim', '|')} {msg}")

    def warn(self, msg: str, indent: int = 2) -> None:
        self._warnings += 1
        pad = " " * indent
        self._out(f"{pad}{self._c('yellow', '[!!]')} {msg}")

    def fail(self, msg: str) -> None:
        self._out(f"  {self._c('red', '[ERR]')} {self._c('bold', msg)}")

    def file_copied(self, src: Path, rel: str) -> None:
        self.assets_copied += 1
        size = fmt_size(src.stat().st_size)
        self.item(f"{src.name}  ({size})  ->  {rel}")

    def summary(self, slides: int, blocks: int) -> None:
        elapsed = time.perf_counter() - self._t0
        self._out()
        self._out(self._c("cyan", "  +---------------------------------------------------+"))
        self._out(
            self._c("cyan", "  |")
            + self._c("green", "  ГОТОВО                                          ")
            + self._c("cyan", "|")
        )
        self._out(self._c("cyan", "  +---------------------------------------------------+"))
        self.ok(f"Блоков:   {blocks}", indent=4)
        self.ok(f"Слайдов:  {slides}", indent=4)
        self.ok(f"Медиа:    {self.assets_copied} файл(ов)", indent=4)
        self.ok(f"Время:    {elapsed:.1f} с", indent=4)
        if self._warnings:
            self.warn(f"Предупреждений: {self._warnings}", indent=4)
        self._out()
        self.item(f"Презентация:  {OUT_DIR / 'index.html'}", indent=4)
        self.item(f"GitHub Pages: {ROOT / 'docs' / 'index.html'}", indent=4)
        self._out()

    def error_block(self, exc: BaseException) -> None:
        self._out()
        self._out(self._c("red", "  +---------------------------------------------------+"))
        self._out(
            self._c("red", "  |")
            + self._c("bold", "  ОШИБКА СБОРКИ                                    ")
            + self._c("red", "|")
        )
        self._out(self._c("red", "  +---------------------------------------------------+"))
        self.fail(str(exc))
        for line in traceback.format_exc().strip().splitlines():
            self._out(self._c("dim", f"    {line}"))
        self._out()


def fmt_size(num: int) -> str:
    if num < 1024:
        return f"{num} B"
    if num < 1024 * 1024:
        return f"{num / 1024:.1f} KB"
    return f"{num / (1024 * 1024):.1f} MB"


def configure_console() -> None:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
        os.system("")  # enable ANSI on Windows


def wait_before_exit() -> None:
    if os.environ.get("BUILD_NO_WAIT"):
        return
    print()
    print("  " + "-" * 52)
    try:
        input("  Нажмите Enter, чтобы закрыть окно... ")
    except EOFError:
        pass


@dataclass
class Block:
    folder: Path
    order_key: str
    block_type: str
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
        p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS
    )


def copy_asset(src: Path, dest_dir: Path, log: BuildLog) -> str:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    shutil.copy2(src, dest)
    rel = dest.relative_to(OUT_DIR).as_posix()
    log.file_copied(src, rel)
    return rel


def generate_placeholder_videos(dest_dir: Path, log: BuildLog, count: int = 3) -> list[Path]:
    try:
        import imageio.v3 as iio
        import numpy as np
    except ImportError:
        log.warn("imageio не установлен — видео-заглушки не созданы")
        return []

    dest_dir.mkdir(parents=True, exist_ok=True)
    palette = [(24, 24, 32), (32, 48, 72), (48, 32, 56)]
    created: list[Path] = []
    log.item("генерация mp4-заглушек...")
    for i in range(count):
        color = palette[i % len(palette)]
        base = np.full((368, 640, 3), color, dtype=np.uint8)
        seq = [
            np.clip(base * (0.85 + 0.15 * ((t % 30) / 29)), 0, 255).astype(np.uint8)
            for t in range(45)
        ]
        target = dest_dir / f"placeholder-{i + 1}.mp4"
        iio.imwrite(target, seq, fps=15, codec="libx264")
        log.file_copied(target, target.relative_to(OUT_DIR).as_posix())
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


def _block_type_label(block_type: str) -> str:
    return {"welcome": "заглушка", "questions": "Q&A", "talk": "выступление"}.get(
        block_type, block_type
    )


def build_slides(blocks: list[Block], log: BuildLog) -> list[dict]:
    slides: list[dict] = []

    for block in blocks:
        asset_dir = OUT_DIR / "assets" / block.order_key
        title = block.meta.get("title", block.order_key)
        author = block.meta.get("author", "")
        type_label = _block_type_label(block.block_type)

        log.phase(f"Блок {block.order_key}  ({type_label})")
        head = f"«{title}»"
        if author:
            head += f"  —  {author}"
        log.ok(head)

        if block.block_type == "welcome":
            videos = list_videos(block.folder)
            if videos:
                log.item(f"фон: {len(videos)} видео")
                video_urls = [copy_asset(v, asset_dir, log) for v in videos]
            else:
                log.warn("нет видео — создаю заглушки")
                placeholders = generate_placeholder_videos(asset_dir, log)
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
            log.ok("слайд: заглушка")
            continue

        if block.block_type == "questions":
            videos = list_videos(block.folder)
            if videos:
                log.item(f"фон: {len(videos)} видео")
                video_urls = [copy_asset(v, asset_dir, log) for v in videos]
            else:
                log.warn("нет видео — создаю заглушки")
                placeholders = generate_placeholder_videos(asset_dir, log)
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
            log.ok("слайд: общие вопросы")
            continue

        refs = referenced_media(block.raw_md)
        talk_meta = {
            "block_title": title,
            "author": author,
        }

        section_names = ("проблема", "инструменты", "решение")
        for key in section_names:
            section_title = "Вопросы?" if key == "вопросы?" else key.capitalize()
            content = block.sections.get(key, "")
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
            log.ok(f"слайд: {section_title}")

        for name in refs:
            src = block.folder / name
            if src.exists():
                copy_asset(src, asset_dir, log)

        demo_intro = block.sections.get("демо", "")
        demo_intro_html = rewrite_asset_urls(
            md_to_html(demo_intro), block.asset_prefix
        )

        demo_files = [
            p
            for p in list_block_media(block.folder, exclude_names={"slide.md"})
            if p.name.lower() not in refs and p.suffix.lower() in DEMO_EXTS
        ]
        demo_files.sort(
            key=lambda p: (0 if p.name.lower().startswith("demo-") else 1, p.name.lower())
        )

        total_demo = len(demo_files)
        if total_demo == 0:
            log.warn("нет файлов demo-* — добавьте видео/фото в папку блока")

        for idx, media in enumerate(demo_files, start=1):
            rel = copy_asset(media, asset_dir, log)
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
            log.ok(f"слайд: Демо {idx}/{total_demo}")

        # вопросы — после демо
        key = "вопросы?"
        content = block.sections.get(key, "")
        html = md_to_html(content)
        html = rewrite_asset_urls(html, block.asset_prefix)
        slides.append(
            {
                "type": "section",
                "block_id": block.order_key,
                "section": key,
                "section_title": "Вопросы?",
                "step_id": key,
                "html": html,
                **talk_meta,
            }
        )
        log.ok("слайд: Вопросы?")

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


def clean_out(log: BuildLog) -> None:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
        log.ok("каталог out/ очищен")
    OUT_DIR.mkdir(parents=True)


def copy_to_docs(log: BuildLog) -> None:
    docs = ROOT / "docs"
    if docs.exists():
        shutil.rmtree(docs)
    shutil.copytree(OUT_DIR, docs)
    log.ok("скопировано в docs/ (GitHub Pages)")


def render_index(slides: list[dict], meta: dict, log: BuildLog) -> None:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("presentation.html.j2")
    html = template.render(
        slides_json=json.dumps(slides, ensure_ascii=False),
        presentation_title=meta.get("presentation_title", "Выступление"),
    )
    out_file = OUT_DIR / "index.html"
    out_file.write_text(html, encoding="utf-8")
    log.ok(f"index.html  ({fmt_size(out_file.stat().st_size)})")


def collect_blocks(log: BuildLog) -> list[Block]:
    if not IN_DIR.exists():
        raise FileNotFoundError(f"Каталог {IN_DIR} не найден")

    folders = sorted(
        p for p in IN_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")
    )
    if not folders:
        raise FileNotFoundError(f"В {IN_DIR} нет папок блоков")

    blocks = [load_block(folder) for folder in folders]
    for b in blocks:
        log.item(f"{b.order_key}/slide.md")
    return blocks


def main() -> int:
    log = BuildLog()
    log.banner()

    log.phase("Чтение блоков")
    blocks = collect_blocks(log)
    log.ok(f"найдено блоков: {len(blocks)}")

    log.phase("Подготовка out/")
    clean_out(log)

    log.phase("Сборка слайдов и копирование медиа")
    slides = build_slides(blocks, log)

    log.phase("Генерация HTML")
    presentation_title = (
        blocks[0].meta.get("title", "Выступление") if blocks else "Выступление"
    )
    render_index(slides, {"presentation_title": presentation_title}, log)

    log.phase("Публикация docs/")
    copy_to_docs(log)

    log.summary(slides=len(slides), blocks=len(blocks))
    return 0


if __name__ == "__main__":
    configure_console()
    exit_code = 1
    log = BuildLog()
    try:
        exit_code = main()
    except Exception as exc:
        log.error_block(exc)
        exit_code = 1
    finally:
        wait_before_exit()
    sys.exit(exit_code)
