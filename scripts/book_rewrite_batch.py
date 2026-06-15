#!/usr/bin/env python3
"""Batch wrapper for the Quarto rewrite adapter."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


DEFAULT_SERVICE_ROOT = Path("/Users/cchizinski2/Dev/research-bench/co-researcher-service")
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_MODEL = "openai/gpt-oss-120b:free"


def main() -> int:
    parser = argparse.ArgumentParser(description="Rewrite multiple Quarto chapters with the local adapter.")
    parser.add_argument("files", nargs="+", type=Path, help="Chapter .qmd files to rewrite")
    parser.add_argument(
        "--mode",
        choices=["rewrite", "expand"],
        default="rewrite",
        help="Adapter mode to use for each chapter",
    )
    parser.add_argument(
        "--preset",
        choices=["openrouter", "dry-run", "custom"],
        default="openrouter",
        help="Convenience preset for the rewrite backend",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Optional output directory for rewritten chapters; defaults to each file's sibling rewrite path",
    )
    parser.add_argument(
        "--service-root",
        type=Path,
        default=DEFAULT_SERVICE_ROOT,
        help="Path to the co-researcher-service checkout",
    )
    parser.add_argument("--writer-provider", help="Custom service writer provider override")
    parser.add_argument("--writer-model", help="Custom service writer model override")
    parser.add_argument("--writer-base-url", help="Custom service writer base URL override")
    parser.add_argument("--writer-api-key", help="Custom service writer API key override")
    parser.add_argument("--writer-temperature", type=float, help="Custom service writer temperature override")
    parser.add_argument("--writer-timeout", type=int, help="Custom service writer timeout override")
    parser.add_argument("--polish-writer-provider", help="Custom expansion polish writer provider override")
    parser.add_argument("--polish-writer-model", help="Custom expansion polish writer model override")
    parser.add_argument("--polish-writer-base-url", help="Custom expansion polish writer base URL override")
    parser.add_argument("--polish-writer-api-key", help="Custom expansion polish writer API key override")
    parser.add_argument("--polish-writer-temperature", type=float, help="Custom expansion polish writer temperature override")
    parser.add_argument("--polish-writer-timeout", type=int, help="Custom expansion polish writer timeout override")
    parser.add_argument("--rewrite-command", help="Optional custom rewrite command template")
    parser.add_argument("--brief", type=Path, help="Optional chapter brief file for expand mode")
    parser.add_argument("--dry-run", action="store_true", help="Force dry-run mode regardless of preset")
    parser.add_argument("--keep-masked", action="store_true", help="Keep masked intermediate files")
    args = parser.parse_args()

    for input_path in args.files:
        if not input_path.exists():
            parser.error(f"Input file not found: {input_path}")
        command = build_command(args, input_path)
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


def build_command(args: argparse.Namespace, input_path: Path) -> list[str]:
    script = Path(__file__).with_name("book_rewrite_adapter.py")
    command = [sys.executable, str(script), str(input_path)]

    if args.mode == "expand":
        command.extend(["--mode", "expand"])

    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        command.extend(["--output", str(args.output_dir / f"{input_path.stem}.rewritten.qmd")])

    if args.brief:
        command.extend(["--brief", str(args.brief)])

    for flag, value in (
        ("--polish-writer-provider", args.polish_writer_provider),
        ("--polish-writer-model", args.polish_writer_model),
        ("--polish-writer-base-url", args.polish_writer_base_url),
        ("--polish-writer-api-key", args.polish_writer_api_key),
        ("--polish-writer-temperature", args.polish_writer_temperature),
        ("--polish-writer-timeout", args.polish_writer_timeout),
    ):
        if value is None:
            continue
        command.extend([flag, str(value)])

    if args.keep_masked:
        command.append("--keep-masked")

    if args.dry_run or args.preset == "dry-run":
        command.append("--dry-run")
        return command

    if args.rewrite_command:
        command.extend(["--rewrite-command", args.rewrite_command])

    if args.preset == "openrouter":
        api_key = args.writer_api_key or os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            parser_error = argparse.ArgumentParser(prog="book_rewrite_batch.py")
            parser_error.error("OPENROUTER_API_KEY is required for the openrouter preset")
        command.extend(
            [
                "--service-root",
                str(args.service_root),
                "--writer-provider",
                "openai-compatible",
                "--writer-base-url",
                DEFAULT_OPENROUTER_BASE_URL,
                "--writer-model",
                DEFAULT_OPENROUTER_MODEL,
                "--writer-api-key",
                str(api_key),
                "--writer-timeout",
                str(args.writer_timeout or 300),
            ]
        )
        return command

    command.extend(["--service-root", str(args.service_root)])
    for flag, value in (
        ("--writer-provider", args.writer_provider),
        ("--writer-model", args.writer_model),
        ("--writer-base-url", args.writer_base_url),
        ("--writer-api-key", args.writer_api_key),
        ("--writer-temperature", args.writer_temperature),
        ("--writer-timeout", args.writer_timeout),
    ):
        if value is None:
            continue
        command.extend([flag, str(value)])
    return command


if __name__ == "__main__":
    raise SystemExit(main())
