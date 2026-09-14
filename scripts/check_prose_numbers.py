#!/usr/bin/env python3
"""Fail when a number written into prose no longer appears in the rendered output.

WHY THIS EXISTS

The book cites computed results in prose as plain literals -- "the overall CPUE
estimate is 1.51 fish per angler-hour". Every one of those was correct when it
was typed. Nothing tells you when it stops being correct.

That is not hypothetical. Between tidycreel 5.0.0 and 7.0.0 the book kept
building and kept publishing numbers the package no longer produced, and the
drift was found only by diffing a fresh render against the live site months
later. A stale literal is silent by construction: it renders, it reads
plausibly, and no test covers prose.

This check closes that gap the cheap way. It does not try to compute anything.
It asks one question per number: does this value still appear anywhere in the
rendered output of the chapter that cites it? If a chapter's prose says 1.51 and
the chapter no longer contains 1.51, either the estimate moved or the sentence
was always wrong. Both are worth a human look.

WHAT IT DELIBERATELY DOES NOT DO

It does not verify that a number means what the sentence claims. "The CV is 3.8%,
within the 10-20% range" passes here, because 3.8% is present -- that sentence
was wrong for a different reason and a numeric check cannot catch it. This finds
drift, not misinterpretation.

It also cannot tell a cited result from a coincidence. If a chapter happens to
render 1.51 somewhere unrelated, a stale 1.51 in prose still passes. The check is
a floor, not a proof.

USAGE

    python3 scripts/check_prose_numbers.py           # after `quarto render`
    python3 scripts/check_prose_numbers.py --list    # show every number checked

Exits 1 when a cited number is missing from its chapter's rendered output.

Numbers that are illustrative rather than computed -- "an estimate of 19,000 fish
reads as though it applies to the whole lake" -- belong in ALLOWLIST below, with
the reason. Adding one is a claim that the number is not a result.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOK = ROOT / "_book"

# Values that are illustrative, hypothetical, or external benchmarks -- not
# results this book computes. Keyed by chapter stem; "*" applies everywhere.
ALLOWLIST: dict[str, set[str]] = {
    "16-reporting-and-interpretation": {
        "19,000",  # hypothetical estimate used to explain domain labelling
        "33,000",  # hypothetical effort figure used to explain units
    },
    "17-case-study-reservoir-creel-survey": {
        "1.51",  # Harlan's CPUE, quoted as a cross-lake comparison
    },
    "18-case-study-harlan-reservoir": {
        "5.3",  # Cedar Lake's effort CV, quoted as a cross-lake comparison
    },
}

# A result-shaped literal: any decimal, or a thousands-separated integer. Bare
# integers are excluded (years, section numbers, "12 days") -- too noisy to be
# useful.
#
# Single-decimal values are INCLUDED deliberately. The first version of this
# check required two or more decimal places, which read as a sensible noise
# filter and would have missed the entire class of drift that prompted it: the
# CVs that moved between 5.0.0 and 7.0.0 were 10.8 -> 11.3, 12.1 -> 12.7,
# 23.2 -> 23.9, and the retention figure went 36.2% -> 38.8%. A guard tuned to
# miss the defect it was built for is worse than no guard, because it reports
# success. Noise is handled by ALLOWLIST instead.
NUMBER = re.compile(r"(?<![\w.#-])(\d{1,3}(?:,\d{3})+|\d+\.\d+)(?![\w])")

# Inline R expressions already recompute on render; they cannot go stale.
INLINE_R = re.compile(r"`r [^`]*`")

FENCE = re.compile(r"^\s*(```|:::)")


def rendered_path(qmd: Path) -> Path:
    rel = qmd.relative_to(ROOT).with_suffix(".html")
    return BOOK / rel


def prose_numbers(qmd: Path) -> list[tuple[int, str]]:
    """Numeric literals in prose, with line numbers. Code blocks excluded."""
    found: list[tuple[int, str]] = []
    in_code = False
    for lineno, raw in enumerate(qmd.read_text(encoding="utf-8").splitlines(), 1):
        if raw.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code or raw.lstrip().startswith("#|"):
            continue
        line = INLINE_R.sub("", raw)
        for m in NUMBER.finditer(line):
            found.append((lineno, m.group(1)))
    return found


def rendered_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    return html.unescape(re.sub(r"<[^>]+>", " ", raw))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="print every number checked")
    args = ap.parse_args()

    if not BOOK.exists():
        print("_book/ not found -- run `quarto render` first.", file=sys.stderr)
        return 2

    qmds = sorted(
        [*(ROOT / "chapters").glob("*.qmd"), *(ROOT / "appendices").glob("*.qmd")]
    )

    misses: list[tuple[str, int, str]] = []
    checked = skipped = 0

    for qmd in qmds:
        stem = qmd.stem
        out = rendered_path(qmd)
        if not out.exists():
            print(f"  skip {stem}: not rendered")
            continue
        text = rendered_text(out)
        allowed = ALLOWLIST.get(stem, set()) | ALLOWLIST.get("*", set())

        for lineno, value in prose_numbers(qmd):
            if value in allowed:
                skipped += 1
                continue
            checked += 1
            # Accept the literal, or the same value without thousands separators,
            # since the renderer is not obliged to format it the way prose does.
            variants = {value, value.replace(",", "")}
            if not any(v in text for v in variants):
                misses.append((stem, lineno, value))
            elif args.list:
                print(f"  ok   {stem}:{lineno} {value}")

    print(f"\nChecked {checked} prose numbers across {len(qmds)} files "
          f"({skipped} allowlisted).")

    if not misses:
        print("All cited numbers still appear in their chapter's rendered output.")
        return 0

    print(f"\n{len(misses)} cited number(s) no longer appear in the rendered output:\n")
    for stem, lineno, value in misses:
        print(f"  {stem}.qmd:{lineno}  {value}")
    print(
        "\nEach one is either a result that moved or a sentence that was always\n"
        "wrong. Re-read the sentence against the rendered chapter; if the number\n"
        "is illustrative rather than computed, add it to ALLOWLIST with a reason."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
