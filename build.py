#!/usr/bin/env python3
"""Copy the runtime HTML presentation into out/ for legacy workflows.

The presentation is no longer compiled from in/. The committed index.html reads
in/ directly in the browser when the page is opened.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "out"
INDEX_FILE = ROOT / "index.html"

_ANSI = {
    "reset": "\033[0m",
    "dim": "\033[2m",
    "bold": "\033[1m",
    "green": "\033[32m",
    "cyan": "\033[36m",
    "red": "\033[31m",
}


class BuildLog:
    """Small console log for the compatibility copy step."""

    def __init__(self) -> None:
        self._use_color = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
        self._t0 = time.perf_counter()

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
            + self._c("bold", "       RUNTIME HTML-ПРЕЗЕНТАЦИЯ                   ")
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

    def fail(self, msg: str) -> None:
        self._out(f"  {self._c('red', '[ERR]')} {self._c('bold', msg)}")

    def summary(self) -> None:
        elapsed = time.perf_counter() - self._t0
        self._out()
        self._out(self._c("cyan", "  +---------------------------------------------------+"))
        self._out(
            self._c("cyan", "  |")
            + self._c("green", "  ГОТОВО                                          ")
            + self._c("cyan", "|")
        )
        self._out(self._c("cyan", "  +---------------------------------------------------+"))
        self.ok("Режим:    runtime-чтение каталога in/", indent=4)
        self.ok(f"Время:    {elapsed:.1f} с", indent=4)
        self._out()
        self.item(f"HTML:  {OUT_DIR / 'index.html'}", indent=4)
        self._out()

    def error_block(self, exc: BaseException) -> None:
        self._out()
        self._out(self._c("red", "  +---------------------------------------------------+"))
        self._out(
            self._c("red", "  |")
            + self._c("bold", "  ОШИБКА                                           ")
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


def clean_out(log: BuildLog) -> None:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
        log.ok("каталог out/ очищен")
    OUT_DIR.mkdir(parents=True)


def copy_index(log: BuildLog) -> None:
    if not INDEX_FILE.is_file():
        raise FileNotFoundError(f"Нет {INDEX_FILE}")
    out_file = OUT_DIR / "index.html"
    shutil.copy2(INDEX_FILE, out_file)
    log.ok(f"index.html  ({fmt_size(out_file.stat().st_size)})")


def main() -> int:
    log = BuildLog()
    log.banner()

    log.phase("Подготовка out/")
    clean_out(log)

    log.phase("Копирование runtime HTML")
    copy_index(log)

    log.summary()
    return 0


if __name__ == "__main__":
    configure_console()
    exit_code = 1
    log = BuildLog()
    try:
        exit_code = main()
    except Exception as exc:
        log.error_block(exc)
    finally:
        wait_before_exit()
    raise SystemExit(exit_code)
