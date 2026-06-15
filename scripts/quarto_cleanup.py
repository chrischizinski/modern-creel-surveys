#!/usr/bin/env python3
"""Conservative cleanup for Quarto Markdown structure.

This module normalizes common block spacing issues without rewriting prose.
It is intentionally narrow: the goal is to repair generated `.qmd` structure,
not to reflow text or change content.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

from citation_suggestions_bridge import generate_citation_suggestions


HEADING_RE = re.compile(r"^(?P<indent>\s{0,3})(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$")
LIST_ITEM_RE = re.compile(r"^\s{0,3}(?:[-+*]|\d+[.)])\s+")
QUOTE_RE = re.compile(r"^\s{0,3}>\s?")
HORIZONTAL_RULE_RE = re.compile(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$")
FENCE_OPEN_RE = re.compile(r"^(\s*)([`~:]{3,})(.*)$")


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean up Quarto Markdown block formatting.")
    parser.add_argument("input", type=Path, help="Input .qmd file")
    parser.add_argument(
        "--output",
        type=Path,
        help="Output .qmd file (default: <input>.cleaned.qmd)",
    )
    parser.add_argument(
        "--validate-render",
        action="store_true",
        help="Run `quarto render` on the cleaned file after writing it",
    )
    args = parser.parse_args()

    if not args.input.exists():
        parser.error(f"Input file not found: {args.input}")

    output_path = args.output or args.input.with_name(f"{args.input.stem}.cleaned.qmd")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cleaned = cleanup_qmd_text(args.input.read_text(encoding="utf-8"))
    output_path.write_text(cleaned, encoding="utf-8")
    print(f"Wrote cleaned chapter to {output_path}", file=sys.stderr)

    suggestions_path = generate_citation_suggestions(cleaned, output_path)
    if suggestions_path is not None:
        print(f"Wrote citation suggestions to {suggestions_path}", file=sys.stderr)

    if args.validate_render:
        validate_render(output_path)
    return 0


def cleanup_qmd_text(text: str) -> str:
    front_matter, body = split_front_matter(text)
    cleaned_body = cleanup_qmd_body(body)
    if front_matter:
        return front_matter + ("\n" if not front_matter.endswith("\n") else "") + cleaned_body
    return cleaned_body


def split_front_matter(text: str) -> tuple[str, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return "", text

    for idx in range(1, len(lines)):
        if lines[idx].strip() in {"---", "..."}:
            front_matter = "".join(lines[: idx + 1])
            body = "".join(lines[idx + 1 :])
            return front_matter, body

    return "", text


def cleanup_qmd_body(body: str) -> str:
    lines = body.splitlines()
    blocks: list[list[str]] = []
    i = 0

    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue

        block, i = consume_block(lines, i)
        if block:
            blocks.append(block)

    flattened: list[str] = []
    for block in blocks:
        if flattened:
            flattened.append("")
        flattened.extend(block)

    return "\n".join(flattened).rstrip() + ("\n" if flattened else "")


def consume_block(lines: list[str], start: int) -> tuple[list[str], int]:
    line = lines[start].rstrip()

    if is_fence_open(line):
        return consume_fence_block(lines, start)
    if is_heading(line):
        return [line], start + 1
    if is_horizontal_rule(line):
        return [line], start + 1
    if is_quote_line(line):
        return consume_quote_block(lines, start)
    if is_list_item(line):
        return consume_list_block(lines, start)
    return consume_paragraph_block(lines, start)


def consume_fence_block(lines: list[str], start: int) -> tuple[list[str], int]:
    opening = lines[start].rstrip()
    match = FENCE_OPEN_RE.match(opening)
    if not match:
        raise ValueError("Internal fence parsing error")
    block: list[str] = [opening]
    fence_marker = match.group(2)
    fence_char = fence_marker[0]
    fence_len = len(fence_marker)
    i = start + 1

    while i < len(lines):
        current = lines[i].rstrip()
        block.append(current)
        if is_fence_close(current, fence_char, fence_len):
            return block, i + 1
        i += 1

    raise ValueError("Unclosed fenced block in Quarto content")


def consume_quote_block(lines: list[str], start: int) -> tuple[list[str], int]:
    block: list[str] = [lines[start].rstrip()]
    i = start + 1

    while i < len(lines):
        current = lines[i].rstrip()
        if not current.strip() or not is_quote_line(current):
            break
        block.append(current)
        i += 1

    return block, i


def consume_list_block(lines: list[str], start: int) -> tuple[list[str], int]:
    block: list[str] = [lines[start].rstrip()]
    i = start + 1

    while i < len(lines):
        current = lines[i].rstrip()
        if not current.strip():
            break
        if is_list_item(current) or is_list_continuation(current):
            block.append(current)
            i += 1
            continue
        break

    return block, i


def consume_paragraph_block(lines: list[str], start: int) -> tuple[list[str], int]:
    block: list[str] = [lines[start].rstrip()]
    i = start + 1

    while i < len(lines):
        current = lines[i].rstrip()
        if not current.strip():
            break
        if is_block_start(current):
            break
        block.append(current)
        i += 1

    return block, i


def is_block_start(line: str) -> bool:
    return any(
        (
            is_heading(line),
            is_horizontal_rule(line),
            is_list_item(line),
            is_quote_line(line),
            is_fence_open(line),
        )
    )


def is_heading(line: str) -> bool:
    return bool(HEADING_RE.match(line))


def is_list_item(line: str) -> bool:
    return bool(LIST_ITEM_RE.match(line))


def is_list_continuation(line: str) -> bool:
    return bool(re.match(r"^\s{4,}\S", line))


def is_quote_line(line: str) -> bool:
    return bool(QUOTE_RE.match(line))


def is_horizontal_rule(line: str) -> bool:
    return bool(HORIZONTAL_RULE_RE.match(line))


def is_fence_open(line: str) -> bool:
    return bool(FENCE_OPEN_RE.match(line))


def is_fence_close(line: str, fence_char: str, fence_len: int) -> bool:
    stripped = line.strip()
    return bool(re.fullmatch(rf"{re.escape(fence_char)}{{{fence_len},}}", stripped))


def validate_render(path: Path) -> None:
    completed = subprocess.run(
        ["quarto", "render", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Quarto render validation failed.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
