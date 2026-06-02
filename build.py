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
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS

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
        os.system("")


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
    preamble: str = ""
    sections: list[tuple[str, str]] = field(default_factory=list)
    raw_md: str = ""
    asset_prefix: str = ""


@dataclass
class AssetContext:
    block: Block
    asset_dir: Path
    log: BuildLog
    copied: dict[str, str] = field(default_factory=dict)

    def rel_url(self, src: Path) -> str:
        return f"{self.block.asset_prefix}/{src.name}"


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return {}, text
    meta = yaml.safe_load(match.group(1)) or {}
    body = text[match.end() :]
    return meta, body


def split_document(body: str) -> tuple[str, list[tuple[str, str]]]:
    """Разбивает тело slide.md на преамбулу и упорядоченные секции ##."""
    preamble_lines: list[str] = []
    sections: list[tuple[str, str]] = []
    current_title: str | None = None
    buffer: list[str] = []

    for line in body.splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line.strip())
        if heading:
            if current_title is not None:
                sections.append((current_title, "\n".join(buffer).strip()))
            else:
                preamble_lines.extend(buffer)
            current_title = heading.group(1).strip()
            buffer = []
            continue
        if current_title is None:
            preamble_lines.append(line)
        else:
            buffer.append(line)

    if current_title is not None:
        sections.append((current_title, "\n".join(buffer).strip()))

    preamble = "\n".join(preamble_lines).strip()
    preamble = re.sub(r"^---+\s*$", "", preamble, flags=re.MULTILINE).strip()
    return preamble, sections


def md_to_html(text: str) -> str:
    if not text.strip():
        return ""
    return markdown.markdown(text, extensions=MD_EXTENSIONS)


def normalize_media_bullets(text: str) -> str:
    """Строки `- `file.png`` превращает в markdown-картинки."""
    lines: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^-\s+`([^`]+)`\s*$", line.strip())
        if match and Path(match.group(1)).suffix.lower() in MEDIA_EXTS:
            name = match.group(1)
            lines.append(f"![{name}]({name})")
        else:
            lines.append(line)
    return "\n".join(lines)


_MEDIA_REF_RE = re.compile(
    r"\.(?:svg|png|jpe?g|gif|webp|mp4|webm|mov|m4v)$", re.IGNORECASE
)


def _is_media_filename(name: str) -> bool:
    return bool(_MEDIA_REF_RE.search(name.strip()))


def extract_demo_media(content: str) -> tuple[str, list[str]]:
    """Из секции ## Демо: текст без медиа-строк и упорядоченные ссылки на файлы."""
    intro_lines: list[str] = []
    refs: list[str] = []

    for line in content.splitlines():
        stripped = line.strip()

        img = re.search(r"!\[[^\]]*\]\(([^)]+)\)", stripped)
        if img:
            ref = img.group(1).strip().split()[0]
            if _is_media_filename(ref):
                refs.append(ref)
                continue

        video = re.search(r"<video[^>]+src=[\"']([^\"']+)[\"']", stripped, re.I)
        if video:
            refs.append(video.group(1).strip())
            continue

        bullet = re.match(r"^-\s+`?([^`\s]+)`?\s*$", stripped)
        if bullet and _is_media_filename(bullet.group(1)):
            refs.append(bullet.group(1).strip())
            continue

        intro_lines.append(line)

    intro = "\n".join(intro_lines).strip()
    return intro, refs


def resolve_demo_files(
    folder: Path, refs: list[str], copied: dict[str, str], log: BuildLog, block_label: str
) -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()

    for ref in refs:
        src = resolve_media_path(folder, ref)
        if src is None:
            log.warn(f"{block_label}: в ## Демо не найден файл «{ref}»")
            continue
        key = src.name.lower()
        if key in seen:
            continue
        seen.add(key)
        files.append(src)

    for path in list_unreferenced_media(folder, copied):
        key = path.name.lower()
        if key not in seen:
            seen.add(key)
            files.append(path)

    files.sort(
        key=lambda p: (0 if p.name.lower().startswith("demo-") else 1, p.name.lower())
    )
    return files


def resolve_media_path(folder: Path, ref: str) -> Path | None:
    ref = ref.strip().split()[0]
    if ref.startswith(("http://", "https://", "data:", "#", "mailto:")):
        return None

    clean = ref.lstrip("./")
    candidates: list[Path] = [
        folder / clean,
        folder / Path(clean).name,
    ]
    for prefix in ("assets/", "videos/", "demo/"):
        if clean.startswith(prefix):
            tail = clean[len(prefix) :]
            candidates.extend([folder / tail, folder / Path(tail).name])

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file():
            return candidate

    name = Path(clean).name
    stem, suffix = Path(name).stem, Path(name).suffix
    if suffix.lower() in MEDIA_EXTS and "-" in stem:
        prefix, tail = stem.split("-", 1)
        if prefix.isdigit():
            for path in folder.iterdir():
                if not path.is_file() or path.suffix.lower() != suffix.lower():
                    continue
                parts = path.stem.split("-", 1)
                if len(parts) == 2 and parts[1] == tail:
                    return path
    return None


def copy_asset(src: Path, dest_dir: Path, log: BuildLog) -> str:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    shutil.copy2(src, dest)
    rel = dest.relative_to(OUT_DIR).as_posix()
    log.file_copied(src, rel)
    return rel


def ensure_asset(
    ctx: AssetContext, ref: str, *, block_label: str
) -> str | None:
    if ref.startswith(("http://", "https://", "data:", "#", "mailto:")):
        return ref

    cache_key = ref.strip().lower()
    if cache_key in ctx.copied:
        return ctx.copied[cache_key]

    src = resolve_media_path(ctx.block.folder, ref)
    if src is None:
        ctx.log.warn(
            f"{block_label}: пропущена ссылка — файл не найден: «{ref}»"
        )
        return None

    rel = copy_asset(src, ctx.asset_dir, ctx.log)
    ctx.copied[cache_key] = rel
    ctx.copied[src.name.lower()] = rel
    return rel


def rewrite_html_assets(html: str, ctx: AssetContext, *, block_label: str) -> str:
    def img_repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        src_match = re.search(r'src="([^"]+)"', tag)
        if not src_match:
            return tag
        url = ensure_asset(ctx, src_match.group(1), block_label=block_label)
        if url is None:
            return ""
        if url.startswith(("http://", "https://")):
            return tag
        return re.sub(r'src="[^"]+"', f'src="{url}"', tag)

    html = re.sub(r"<img[^>]+src=\"[^\"]+\"[^>]*>", img_repl, html)

    def video_repl(match: re.Match[str]) -> str:
        src = match.group(2)
        url = ensure_asset(ctx, src, block_label=block_label)
        if url is None:
            return ""
        attrs = match.group(1)
        poster_match = re.search(r'poster="([^"]+)"', attrs)
        if poster_match:
            poster_url = ensure_asset(
                ctx, poster_match.group(1), block_label=block_label
            )
            if poster_url is None:
                attrs = re.sub(r'\s*poster="[^"]+"', "", attrs)
            else:
                attrs = re.sub(
                    r'poster="[^"]+"', f'poster="{poster_url}"', attrs
                )
        return f'<video{attrs} src="{url}"></video>'

    html = re.sub(r"<video([^>]*)\ssrc=\"([^\"]+)\"[^>]*></video>", video_repl, html)
    html = re.sub(r"<video([^>]*)\ssrc=\"([^\"]+)\"[^>]*/>", video_repl, html)
    return html


_CONSECUTIVE_IMG_PARAS = re.compile(
    r"(?:<p>\s*<img\s+[^>]*>\s*</p>\s*)+",
    re.IGNORECASE,
)
_IMG_TAG = re.compile(r"(<img\s+[^>]*>)", re.IGNORECASE)


def group_consecutive_images(html: str) -> str:
    """Подряд идущие картинки — в строку слева направо (по две в ряд)."""

    def repl(match: re.Match[str]) -> str:
        imgs = _IMG_TAG.findall(match.group(0))
        rows: list[str] = []
        for i in range(0, len(imgs), 2):
            chunk = imgs[i : i + 2]
            cells = "".join(f'<div class="media-cell">{img}</div>' for img in chunk)
            rows.append(f'<div class="media-row">{cells}</div>')
        return "\n".join(rows)

    return _CONSECUTIVE_IMG_PARAS.sub(repl, html)


def section_to_html(content: str, ctx: AssetContext, *, block_label: str) -> str:
    normalized = normalize_media_bullets(content)
    html = md_to_html(normalized)
    html = rewrite_html_assets(html, ctx, block_label=block_label)
    return group_consecutive_images(html)


def list_folder_videos(folder: Path) -> list[Path]:
    return sorted(
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS
    )


def list_background_videos(block: Block, log: BuildLog) -> list[Path]:
    """Фоновые ролики: из секции ## Фон в slide.md или все mp4 в каталоге."""
    block_label = f"Блок {block.order_key}"
    for section_title, content in block.sections:
        if section_title.strip().lower() not in ("фон", "background"):
            continue
        _, refs = extract_demo_media(content)
        files: list[Path] = []
        for ref in refs:
            src = resolve_media_path(block.folder, ref)
            if src is None:
                log.warn(f"{block_label}: в ## Фон не найден файл «{ref}»")
                continue
            files.append(src)
        if files:
            return sorted(files)

    return list_folder_videos(block.folder)


def list_unreferenced_media(folder: Path, copied: dict[str, str]) -> list[Path]:
    files: list[Path] = []
    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in MEDIA_EXTS:
            continue
        if path.name.lower() == "slide.md":
            continue
        if path.name.lower() in copied:
            continue
        files.append(path)
    files.sort(
        key=lambda p: (0 if p.name.lower().startswith("demo-") else 1, p.name.lower())
    )
    return files


def load_block(folder: Path) -> Block:
    slide_path = folder / "slide.md"
    if not slide_path.exists():
        raise FileNotFoundError(f"Нет slide.md в {folder}")

    raw = slide_path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(raw)
    preamble, sections = split_document(body)
    block_type = meta.get("type", "talk")
    order_key = folder.name

    return Block(
        folder=folder,
        order_key=order_key,
        block_type=block_type,
        meta=meta,
        preamble=preamble,
        sections=sections,
        raw_md=raw,
        asset_prefix=f"assets/{order_key}",
    )


def _block_type_label(block_type: str) -> str:
    return {"welcome": "заглушка", "questions": "Q&A", "talk": "выступление"}.get(
        block_type, block_type
    )


def _step_id(title: str) -> str:
    return title.strip().lower()


def build_welcome_or_questions(
    block: Block, log: BuildLog, slide_type: str
) -> dict:
    asset_dir = OUT_DIR / "assets" / block.order_key
    ctx = AssetContext(block=block, asset_dir=asset_dir, log=log)

    videos = list_background_videos(block, log)
    video_urls: list[str] = []
    if videos:
        log.item(f"фон: {len(videos)} видео")
        for video in videos:
            video_urls.append(copy_asset(video, asset_dir, log))
            ctx.copied[video.name.lower()] = video_urls[-1]
    else:
        log.item("фон: без видео")

    title = block.meta.get("title", block.order_key)
    payload: dict = {
        "type": slide_type,
        "title": title,
        "subtitle": block.meta.get("subtitle", ""),
        "videos": video_urls,
        "block_id": block.order_key,
    }

    if slide_type == "questions":
        text_key = "текст"
        for section_title, content in block.sections:
            if section_title.strip().lower() == text_key:
                payload["html"] = section_to_html(
                    content, ctx, block_label=f"Блок {block.order_key}"
                )
                break
        else:
            payload["html"] = ""

    return payload


def build_talk_slides(block: Block, log: BuildLog) -> list[dict]:
    asset_dir = OUT_DIR / "assets" / block.order_key
    ctx = AssetContext(block=block, asset_dir=asset_dir, log=log)
    block_label = f"Блок {block.order_key}"

    title = block.meta.get("title", block.order_key)
    author = block.meta.get("author", "")
    talk_meta = {"block_title": title, "author": author}
    slides: list[dict] = []

    if block.preamble.strip():
        html = section_to_html(block.preamble, ctx, block_label=block_label)
        slides.append(
            {
                "type": "section",
                "block_id": block.order_key,
                "section": "intro",
                "section_title": title,
                "step_id": "intro",
                "html": html,
                **talk_meta,
            }
        )
        log.ok("слайд: вступление")

    demo_intro_html = ""
    demo_section_seen = False

    for section_title, content in block.sections:
        key = section_title.strip().lower()

        if key == "демо":
            demo_section_seen = True
            intro_text, demo_refs = extract_demo_media(content)
            demo_intro_html = section_to_html(
                intro_text, ctx, block_label=block_label
            )
            media_files = resolve_demo_files(
                block.folder, demo_refs, ctx.copied, log, block_label
            )
            total = len(media_files)

            if total == 0:
                if demo_intro_html.strip():
                    slides.append(
                        {
                            "type": "section",
                            "block_id": block.order_key,
                            "section": key,
                            "section_title": section_title,
                            "step_id": _step_id(section_title),
                            "html": demo_intro_html,
                            **talk_meta,
                        }
                    )
                    log.ok(f"слайд: {section_title}")
                continue

            for idx, media in enumerate(media_files, start=1):
                rel = copy_asset(media, asset_dir, log)
                ctx.copied[media.name.lower()] = rel
                mime = "video" if media.suffix.lower() in VIDEO_EXTS else "image"
                slides.append(
                    {
                        "type": "demo",
                        "block_id": block.order_key,
                        "src": rel,
                        "mime": mime,
                        "index": idx,
                        "total": total,
                        "step_id": f"демо-{idx}",
                        "intro_html": demo_intro_html if idx == 1 else "",
                        **talk_meta,
                    }
                )
                log.ok(f"слайд: Демо {idx}/{total}")
            continue

        html = section_to_html(content, ctx, block_label=block_label)
        slides.append(
            {
                "type": "section",
                "block_id": block.order_key,
                "section": key,
                "section_title": section_title,
                "step_id": _step_id(section_title),
                "html": html,
                **talk_meta,
            }
        )
        log.ok(f"слайд: {section_title}")

    if not demo_section_seen:
        leftover = list_unreferenced_media(block.folder, ctx.copied)
        if leftover:
            log.warn(
                f"{block_label}: {len(leftover)} медиафайл(ов) не использованы "
                f"(добавьте ## Демо или ссылки в MD): "
                + ", ".join(p.name for p in leftover)
            )

    return slides


def build_slides(blocks: list[Block], log: BuildLog) -> list[dict]:
    slides: list[dict] = []

    for block in blocks:
        title = block.meta.get("title", block.order_key)
        author = block.meta.get("author", "")
        type_label = _block_type_label(block.block_type)

        log.phase(f"Блок {block.order_key}  ({type_label})")
        head = f"«{title}»"
        if author:
            head += f"  —  {author}"
        log.ok(head)

        if block.block_type == "welcome":
            slides.append(build_welcome_or_questions(block, log, "welcome"))
            log.ok("слайд: заглушка")
            continue

        if block.block_type == "questions":
            slides.append(build_welcome_or_questions(block, log, "questions"))
            log.ok("слайд: общие вопросы")
            continue

        slides.extend(build_talk_slides(block, log))

    return slides


def clean_out(log: BuildLog) -> None:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
        log.ok("каталог out/ очищен")
    OUT_DIR.mkdir(parents=True)


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
