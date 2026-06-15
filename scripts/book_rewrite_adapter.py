#!/usr/bin/env python3
"""Book-local Quarto rewrite adapter for `co-researcher-service`.

The adapter keeps Quarto-specific structure in this repository and delegates
prose rewriting to the separate manuscript service when it is available.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import re
import subprocess
import sys
import tempfile
from typing import Iterable

from citation_suggestions_bridge import generate_citation_suggestions
from quarto_cleanup import cleanup_qmd_text


FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
TITLE_RE = re.compile(r"^title:\s*(?P<value>.+?)\s*$", re.IGNORECASE)
HEADING_RE = re.compile(r"^(?P<indent>\s{0,3})(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$")
PLACEHOLDER_RE = re.compile(r"__QMD_PROTECTED_\d{4}__")
PLACEHOLDER_TEMPLATE = "__QMD_PROTECTED_{:04d}__"
PROCESS_NARRATION_RE = re.compile(
    r"^I\s+(will|am|have|had|would|could|should|might|must|can|do|did|'m|'ve|'d|'ll)\b",
    re.IGNORECASE,
)
EXPANSION_CONTRACT_PATH = Path(__file__).resolve().parents[1] / ".ai" / "expansion-contract.md"
DEFAULT_EXPANSION_CONTRACT = """You are drafting book prose from chapter notes.

Write for a methods-first Quarto book, not for an article manuscript.
Use the notes as the governing source. Expand them into clear, finished prose without inventing unsupported facts, package features, citations, or numeric results.
If the notes leave a gap, write a careful placeholder such as [INSERT VALUE] or [AUTHOR YEAR].
Keep the book voice direct, restrained, and instructional.
Do not add heading lines or bullets unless the notes already require them.
"""
DEFAULT_KB_ROOT = Path("/Users/cchizinski2/Dev/knowledge-base")
CREEL_PACK_NAME = "creel_surveys"
CREEL_PACK_NOTE_PATH = Path("packs") / CREEL_PACK_NAME / "notes" / "scientific-manuscript-characteristics.md"
CREEL_PACK_BOOKS_PATH = Path("packs") / CREEL_PACK_NAME / "config" / "books.yaml"
SCREENING_SECTION_HEADINGS = {
    "What Makes a Scientific Manuscript Scientific",
    "Book Chapter",
    "Methods or Estimation Paper",
    "Claims and Inference",
    "Terminology and Consistency",
    "Reproducibility and Traceability",
    "Working Rule of Thumb",
}
SCREENING_STOPWORDS = {
    "about",
    "above",
    "after",
    "again",
    "also",
    "analysis",
    "answer",
    "before",
    "being",
    "book",
    "chapter",
    "could",
    "from",
    "have",
    "into",
    "later",
    "make",
    "more",
    "notes",
    "other",
    "over",
    "package",
    "parts",
    "practical",
    "quickly",
    "should",
    "simple",
    "some",
    "than",
    "that",
    "their",
    "them",
    "these",
    "this",
    "those",
    "through",
    "under",
    "what",
    "when",
    "where",
    "which",
    "with",
    "without",
    "would",
}

CLI_EXPANSION_PROVIDERS = {"agy", "gemini", "gemini-cli"}
SERVICE_EXPANSION_PROVIDERS = {"claude", "openai", "openai-compatible", "ollama"}


@dataclass(slots=True)
class ProtectedBlock:
    placeholder: str
    original: str


@dataclass(slots=True)
class CLIReviewWriter:
    executable: str
    model: str | None = None
    timeout: int | None = None

    def generate(self, prompt: str) -> str:
        command = self._build_command(prompt)
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout,
            )
        except FileNotFoundError as exc:  # pragma: no cover
            raise RuntimeError(f"{self.executable} CLI is not available on PATH") from exc

        if completed.returncode != 0:
            raise RuntimeError(
                f"{self.executable} generation failed: {completed.returncode}:\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )

        output = completed.stdout.strip()
        if not output:
            output = completed.stderr.strip()
        return output + ("\n" if output and not output.endswith("\n") else "")

    def _build_command(self, prompt: str) -> list[str]:
        executable = resolve_cli_executable(self.executable)
        if executable == "agy":
            command = [executable, "--print", prompt]
            if self.model:
                command.extend(["--model", self.model])
            return command

        if executable == "gemini":
            command = [executable]
            if self.model:
                command.extend(["--model", self.model])
            command.extend(["--prompt", prompt])
            return command

        raise RuntimeError(f"Unsupported CLI expansion executable: {executable}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rewrite the prose in a Quarto chapter while preserving protected structure."
    )
    parser.add_argument("input", type=Path, help="Input .qmd file")
    parser.add_argument(
        "--mode",
        choices=["rewrite", "expand"],
        default="rewrite",
        help="Rewrite existing prose or expand chapter notes into fuller prose",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output .qmd file (default: <input>.rewritten.qmd)",
    )
    parser.add_argument(
        "--service-root",
        type=Path,
        help="Path to the co-researcher-service repo root; used to set PYTHONPATH if present",
    )
    parser.add_argument(
        "--rewrite-command",
        help=(
            "Optional command template that rewrites the masked file. "
            "Use {input} and {output} placeholders. If omitted, the adapter "
            "uses the local co-researcher-service CLI when it can find it, or "
            "falls back to a dry run."
        ),
    )
    parser.add_argument(
        "--writer-provider",
        help="Optional service writer provider override, e.g. ollama, claude, or openai-compatible",
    )
    parser.add_argument("--writer-model", help="Optional service writer model override")
    parser.add_argument("--writer-base-url", help="Optional service writer base URL override")
    parser.add_argument("--writer-api-key", help="Optional service writer API key override")
    parser.add_argument("--writer-temperature", type=float, help="Optional service writer temperature override")
    parser.add_argument("--writer-timeout", type=int, help="Optional service writer timeout override")
    parser.add_argument(
        "--polish-writer-provider",
        help="Optional separate provider override for the expansion polish pass",
    )
    parser.add_argument("--polish-writer-model", help="Optional separate model override for the expansion polish pass")
    parser.add_argument("--polish-writer-base-url", help="Optional separate base URL override for the expansion polish pass")
    parser.add_argument("--polish-writer-api-key", help="Optional separate API key override for the expansion polish pass")
    parser.add_argument("--polish-writer-temperature", type=float, help="Optional separate temperature override for the expansion polish pass")
    parser.add_argument("--polish-writer-timeout", type=int, help="Optional separate timeout override for the expansion polish pass")
    parser.add_argument(
        "--brief",
        type=Path,
        help="Optional chapter brief file for expand mode; if provided, the brief is used as the source notes instead of the chapter body",
    )
    parser.add_argument(
        "--knowledge-base-root",
        type=Path,
        help="Optional knowledge-base repo root for creel-pack screening cues",
    )
    parser.add_argument(
        "--no-creel-pack-screening",
        action="store_true",
        help="Skip the creel-pack screening pass even if the knowledge base is available",
    )
    parser.add_argument(
        "--no-polish",
        action="store_true",
        help="Skip the second expansion pass and keep the draft output from the first pass",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip the service call and emit the masked/unmasked file pair locally",
    )
    parser.add_argument(
        "--keep-masked",
        action="store_true",
        help="Write the masked intermediate body next to the output for inspection",
    )
    parser.add_argument(
        "--no-format-cleanup",
        action="store_true",
        help="Skip Quarto block-spacing cleanup before writing the final file",
    )
    args = parser.parse_args()

    input_path: Path = args.input
    if not input_path.exists():
        parser.error(f"Input file not found: {input_path}")

    output_path = args.output or input_path.with_name(f"{input_path.stem}.rewritten.qmd")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    text = input_path.read_text(encoding="utf-8")
    front_matter, body = split_front_matter(text)
    title = extract_title(front_matter) or input_path.stem
    source_sections = split_sections(body)
    brief_text = args.brief.read_text(encoding="utf-8") if getattr(args, "brief", None) else None
    creel_pack_screening = None
    if not args.no_creel_pack_screening:
        creel_pack_screening = load_creel_pack_screening(
            knowledge_base_root=args.knowledge_base_root or detect_knowledge_base_root(),
            chapter_title=title,
            chapter_brief=brief_text,
            sections=source_sections,
        )
        if creel_pack_screening:
            print(f"[expand] creel pack screening complete ({len(creel_pack_screening)} chars)", file=sys.stderr)
    masked_sections = [
        SectionBlock(
            level=section.level,
            title=section.title,
            preface=section.preface,
            body=masked_body,
            protected_blocks=protected_blocks,
        )
        for section in source_sections
        for masked_body, protected_blocks in [mask_protected_blocks(section.body)]
    ]

    if args.keep_masked:
        masked_path = output_path.with_suffix(".masked.md")
        masked_path.write_text(render_sections(masked_sections), encoding="utf-8")
        print(f"Wrote masked intermediate to {masked_path}", file=sys.stderr)

    if args.dry_run:
        output_path.write_text(text, encoding="utf-8")
        print(f"Wrote rewritten chapter to {output_path}", file=sys.stderr)
        return 0
    elif args.mode == "rewrite":
        rewritten_sections = rewrite_sections(
            masked_sections,
            title=title,
            service_root=args.service_root,
            rewrite_command=args.rewrite_command,
            writer_args=extract_writer_args(args),
            work_dir=input_path.parent,
        )
    else:
        rewritten_sections = expand_sections(
            masked_sections,
            title=title,
            service_root=args.service_root,
            draft_writer_args=extract_writer_args(args),
            polish_writer_args=extract_polish_writer_args(args),
            chapter_brief=brief_text,
            creel_pack_screening=creel_pack_screening,
            polish=not args.no_polish,
        )

    final_body = render_sections(
        [
            SectionBlock(
                level=section.level,
                title=section.title,
                preface=section.preface,
                body=unmask_protected_blocks(section.body, section.protected_blocks),
            )
            for section in rewritten_sections
        ]
    )
    final_text = front_matter + final_body
    if not args.no_format_cleanup:
        final_text = cleanup_qmd_text(final_text)
    output_path.write_text(final_text, encoding="utf-8")
    print(f"Wrote rewritten chapter to {output_path}", file=sys.stderr)

    suggestions_path = generate_citation_suggestions(final_text, output_path)
    if suggestions_path is not None:
        print(f"Wrote citation suggestions to {suggestions_path}", file=sys.stderr)
    return 0


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


def extract_title(front_matter: str) -> str | None:
    for line in front_matter.splitlines():
        match = TITLE_RE.match(line.strip())
        if not match:
            continue
        raw_value = match.group("value").strip()
        if raw_value and raw_value[0] in {'"', "'"} and raw_value[-1] == raw_value[0]:
            return raw_value[1:-1]
        return raw_value
    return None


def mask_protected_blocks(body: str) -> tuple[str, list[ProtectedBlock]]:
    lines = body.splitlines(keepends=True)
    output: list[str] = []
    protected: list[ProtectedBlock] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        fence = FENCE_RE.match(line)
        if fence:
            indent = fence.group(1)
            fence_marker = fence.group(2)[0]
            start = i
            i += 1
            while i < len(lines):
                candidate = lines[i]
                if re.match(rf"^\s*{re.escape(fence_marker)}{{3,}}\s*$", candidate):
                    break
                i += 1
            if i < len(lines):
                i += 1
            block = "".join(lines[start:i])
            placeholder = indent + PLACEHOLDER_TEMPLATE.format(len(protected) + 1)
            protected.append(ProtectedBlock(placeholder=placeholder, original=block))
            output.append(placeholder + "\n" if block.endswith("\n") else placeholder)
            continue

        output.append(line)
        i += 1

    return "".join(output), protected


@dataclass(slots=True)
class SectionBlock:
    level: int
    title: str
    preface: str
    body: str
    protected_blocks: list[ProtectedBlock] | None = None


def split_sections(body: str) -> list[SectionBlock]:
    lines = body.splitlines(keepends=True)
    sections: list[SectionBlock] = []
    preface_lines: list[str] = []
    current: SectionBlock | None = None
    current_lines: list[str] = []

    def flush_current() -> None:
        nonlocal current, current_lines
        if current is None:
            return
        current.body = "".join(current_lines).strip("\n")
        sections.append(current)
        current = None
        current_lines = []

    for line in lines:
        match = HEADING_RE.match(line.rstrip("\n"))
        if match:
            flush_current()
            level = len(match.group("marks"))
            title = match.group("title").strip()
            current = SectionBlock(level=level, title=title, preface="", body="")
            continue
        if current is None:
            preface_lines.append(line)
        else:
            current_lines.append(line)

    flush_current()

    if preface_lines:
        sections.insert(
            0,
            SectionBlock(
                level=0,
                title="front matter",
                preface="",
                body="".join(preface_lines).strip("\n"),
            ),
        )

    return sections


def render_sections(sections: list[SectionBlock]) -> str:
    parts: list[str] = []
    for section in sections:
        if section.level == 0 and section.title == "front matter":
            if section.body:
                parts.append(section.body.rstrip("\n"))
            continue
        heading = "#" * section.level
        parts.append(f"{section.preface}{heading} {section.title}\n\n{section.body.rstrip()}\n")
    return "".join(parts)


def unmask_protected_blocks(text: str, protected_blocks: Iterable[ProtectedBlock]) -> str:
    restored = text
    for block in protected_blocks:
        restored = restored.replace(block.placeholder, block.original)
    if PLACEHOLDER_RE.search(restored):
        raise RuntimeError("Rewrite output still contains protected placeholders.")
    return restored


def rewrite_sections(
    sections: list[SectionBlock],
    *,
    title: str,
    service_root: Path | None,
    rewrite_command: str | None,
    writer_args: dict[str, object],
    work_dir: Path,
) -> list[SectionBlock]:
    rewritten: list[SectionBlock] = []
    for section in sections:
        if section.level == 0 and section.title == "front matter":
            rewritten.append(section)
            continue
        rewritten_body = rewrite_section_body(
            section,
            title=title,
            service_root=service_root,
            rewrite_command=rewrite_command,
            writer_args=writer_args,
            work_dir=work_dir,
        )
        rewritten.append(
            SectionBlock(
                level=section.level,
                title=section.title,
                preface=section.preface,
                body=rewritten_body,
                protected_blocks=section.protected_blocks,
            )
        )
    return rewritten


def expand_sections(
    sections: list[SectionBlock],
    *,
    title: str,
    service_root: Path | None,
    draft_writer_args: dict[str, object],
    polish_writer_args: dict[str, object] | None,
    chapter_brief: str | None,
    creel_pack_screening: str | None,
    polish: bool,
) -> list[SectionBlock]:
    service_root = ensure_service_root(service_root)
    ensure_service_src_path(service_root)
    draft_writer = load_expansion_writer(service_root, draft_writer_args)
    polish_config = polish_writer_args if _has_writer_overrides(polish_writer_args) else draft_writer_args
    polish_writer = load_expansion_writer(service_root, polish_config) if polish else None
    brief_sections = split_sections(chapter_brief) if chapter_brief else []
    expansion_contract = load_expansion_contract()
    print("[expand] phase 1: extract canonical entities", file=sys.stderr)
    print(
        f"[expand] phase 2: draft expansion{', then polish' if polish_writer else ''}",
        file=sys.stderr,
    )
    if polish_writer:
        print("[expand] secondary polish pass: enabled", file=sys.stderr)
    else:
        print("[expand] secondary polish pass: skipped", file=sys.stderr)

    from co_researcher_service.workflows.chapter_expansion import (
        ChapterConsistencyRequest,
        ChapterEntityRequest,
        ChapterSectionRequest,
        check_chapter_consistency,
        expand_chapter_section,
        extract_chapter_entities,
    )

    # Phase 0: extract canonical entities from all notes + brief before expanding any section
    all_notes = "\n\n".join(s.body for s in sections if s.level > 0)
    entity_input = "\n\n".join(
        part
        for part in (
            chapter_brief or "",
            creel_pack_screening or "",
            all_notes,
        )
        if part
    ).strip()
    canonical_facts = extract_chapter_entities(
        ChapterEntityRequest(full_text=entity_input, chapter_title=title),
        draft_writer,
    )
    print(f"[expand] entity extraction complete ({len(canonical_facts)} chars)", file=sys.stderr)

    rewritten: list[SectionBlock] = []
    for section in sections:
        if section.level == 0 and section.title == "front matter":
            rewritten.append(section)
            continue
        section_brief = _pick_brief_text(section.title, brief_sections, chapter_brief)
        prior_text = _render_prior_expansion_sections(section.title, rewritten)
        generated = expand_chapter_section(
            ChapterSectionRequest(
                section_title=section.title,
                section_notes=section.body,
                chapter_title=title,
                canonical_facts=canonical_facts,
                prior_sections=prior_text,
                chapter_brief=section_brief or "",
                document_conventions=expansion_contract,
            ),
            writer=draft_writer,
            polish_writer=polish_writer,
        )
        rewritten.append(
            SectionBlock(
                level=section.level,
                title=section.title,
                preface=section.preface,
                body=clean_expanded_body(generated),
                protected_blocks=section.protected_blocks,
            )
        )
        print(f"[expand] section complete: {section.title}", file=sys.stderr)

    # Phase 3: consistency check — write issues to stderr and a sidecar file
    print("[expand] phase 3: consistency check", file=sys.stderr)
    expanded_sections = [(s.title, s.body) for s in rewritten if s.level > 0]
    if expanded_sections:
        issues = check_chapter_consistency(
            ChapterConsistencyRequest(
                chapter_title=title,
                sections=expanded_sections,
                canonical_facts=canonical_facts,
            ),
            polish_writer or draft_writer,
        )
        if issues:
            print(f"[expand] {len(issues)} consistency issue(s) detected:", file=sys.stderr)
            for issue in issues:
                print(f"  - {issue}", file=sys.stderr)
        else:
            print("[expand] consistency check: clean", file=sys.stderr)

    return rewritten


def rewrite_section_body(
    section: SectionBlock,
    *,
    title: str,
    service_root: Path | None,
    rewrite_command: str | None,
    writer_args: dict[str, object],
    work_dir: Path,
) -> str:
    with tempfile.TemporaryDirectory(prefix="creel-book-rewrite-") as tmp:
        tmpdir = Path(tmp)
        input_file = tmpdir / "masked-input.md"
        output_file = tmpdir / "masked-output.md"
        section_input = render_sections([section])
        input_file.write_text(section_input, encoding="utf-8")

        command, env, cwd = build_command(
            input_file=input_file,
            output_file=output_file,
            title=title,
            service_root=service_root,
            rewrite_command=rewrite_command,
            writer_args=writer_args,
            work_dir=work_dir,
        )
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "Rewrite command failed.\n"
                f"Command: {format_command(command)}\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )
        if not output_file.exists():
            raise RuntimeError("Rewrite command completed without creating the expected output file.")
        rewritten_text = output_file.read_text(encoding="utf-8")
        rewritten_sections = split_sections(rewritten_text)
        if not rewritten_sections:
            raise RuntimeError("Rewrite output did not contain any sections.")
        if len(rewritten_sections) == 1 and rewritten_sections[0].level == 0:
            return clean_rewritten_body(rewritten_sections[0].body)
        for candidate in rewritten_sections:
            if candidate.level == section.level and candidate.title.strip().lower() == section.title.strip().lower():
                return clean_rewritten_body(candidate.body)
        for candidate in rewritten_sections:
            if candidate.level == section.level:
                return clean_rewritten_body(candidate.body)
        return clean_rewritten_body(rewritten_sections[-1].body)


def build_expansion_prompt(
    *,
    chapter_title: str,
    section: SectionBlock,
    prior_sections: list[SectionBlock],
    chapter_brief: str | None,
) -> str:
    prior_context = _render_prior_expansion_sections(section.title, prior_sections)
    notes = section.body.strip() or "No additional notes provided."
    brief = chapter_brief.strip() if chapter_brief and chapter_brief.strip() else "No separate chapter brief provided."
    expansion_contract = load_expansion_contract()
    return f"""You are expanding a section of a methods-first Quarto book on modern creel survey analysis in R.

Write the section body as polished textbook prose, not as a manuscript section.

Rules:
- Stay faithful to the source notes. Do not invent methods, package features, citations, or numeric results.
- If a detail is missing, use [INSERT VALUE], [INSERT RESULT], or [AUTHOR YEAR].
- Keep the tone instructional, methods-first, and field-oriented.
- Preserve the meaning of the section title and its role in the chapter.
- Do not mention that this is a rewrite, expansion, draft, or review.
- Do not use article-style abstract/methods/results conventions unless the notes explicitly call for them.
- Avoid generic filler. Explain concepts concretely.
- Return prose only. No heading lines. No bullet list unless the notes already require one.

Book expansion contract:
{expansion_contract}

Chapter title: {chapter_title}
Section title: {section.title}

Prior sections for continuity:
{prior_context}

Chapter brief:
{brief}

Source notes for this section:
{notes}
"""


def polish_expanded_body(
    writer,
    *,
    chapter_title: str,
    section: SectionBlock,
    draft_body: str,
    chapter_brief: str | None,
    prior_sections: list[SectionBlock],
) -> str:
    prior_context = _render_prior_expansion_sections(section.title, prior_sections)
    brief = chapter_brief.strip() if chapter_brief and chapter_brief.strip() else "No separate chapter brief provided."
    prompt = f"""You are polishing a draft section for a methods-first Quarto book on modern creel survey analysis in R.

Tighten the prose without adding new claims or broadening the scope.

Rules:
- Preserve the section's purpose, terminology, and chapter role.
- Remove repetition, generic filler, and manuscript-like phrasing.
- Do not invent methods, package features, citations, named examples, or numeric results.
- Keep placeholders such as [INSERT VALUE], [INSERT RESULT], and [AUTHOR YEAR] if the draft still needs them.
- Do not add headings or bullet lists.
- Return prose only.

Chapter title: {chapter_title}
Section title: {section.title}

Chapter brief:
{brief}

Prior sections for continuity:
{prior_context}

Draft to polish:
{draft_body.strip() or "No draft text provided."}
"""
    return clean_expanded_body(writer.generate(prompt).strip())


def _render_prior_expansion_sections(section_title: str, prior_sections: list[SectionBlock]) -> str:
    parts: list[str] = []
    for section in prior_sections:
        if section.level == 0 and section.title == "front matter":
            continue
        if section.title == section_title:
            continue
        if not section.body.strip():
            continue
        parts.append(f"### {section.title}\n\n{section.body}")
    return "\n\n".join(parts) if parts else "No prior sections available."


def clean_expanded_body(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        if line.strip() == "---":
            continue
        if _is_process_narration(line):
            continue
        lines.append(line)
    return "\n".join(lines).strip("\n")


def clean_rewritten_body(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if line.strip() == "---":
            continue
        if _is_process_narration(line):
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip("\n")
    return cleaned


def _is_process_narration(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return bool(PROCESS_NARRATION_RE.match(stripped))


def build_command(
    *,
    input_file: Path,
    output_file: Path,
    title: str,
    service_root: Path | None,
    rewrite_command: str | None,
    writer_args: dict[str, object],
    work_dir: Path,
) -> tuple[list[str], dict[str, str], Path]:
    env = os.environ.copy()
    cwd = work_dir
    if rewrite_command:
        import shlex

        command = [part.format(input=input_file, output=output_file, title=title) for part in shlex.split(rewrite_command)]
        return command, env, cwd

    discovered_root = service_root or detect_service_root()
    if discovered_root is None:
        # Dry-run fallback: keep the masked file unchanged.
        output_file.write_text(input_file.read_text(encoding="utf-8"), encoding="utf-8")
        return [sys.executable, "-c", "pass"], env, cwd

    service_python = detect_service_python(discovered_root)
    env["PYTHONPATH"] = f"{discovered_root / 'src'}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    cwd = discovered_root
    command = [
        str(service_python),
        "-m",
        "co_researcher_service.interfaces.cli",
        "manuscript-rewrite",
        "--input",
        str(input_file),
        "--output",
        str(output_file),
        "--title",
        title,
    ]
    command.extend(_writer_cli_args(writer_args))
    return command, env, cwd


def extract_writer_args(args: argparse.Namespace) -> dict[str, object]:
    return {
        "provider": getattr(args, "writer_provider", None),
        "model": getattr(args, "writer_model", None),
        "base_url": getattr(args, "writer_base_url", None),
        "api_key": getattr(args, "writer_api_key", None),
        "temperature": getattr(args, "writer_temperature", None),
        "timeout": getattr(args, "writer_timeout", None),
    }


def extract_polish_writer_args(args: argparse.Namespace) -> dict[str, object]:
    return {
        "provider": getattr(args, "polish_writer_provider", None),
        "model": getattr(args, "polish_writer_model", None),
        "base_url": getattr(args, "polish_writer_base_url", None),
        "api_key": getattr(args, "polish_writer_api_key", None),
        "temperature": getattr(args, "polish_writer_temperature", None),
        "timeout": getattr(args, "polish_writer_timeout", None),
    }


def _has_writer_overrides(writer_args: dict[str, object] | None) -> bool:
    if not writer_args:
        return False
    return any(value is not None for value in writer_args.values())


def load_expansion_writer(service_root: Path | None, writer_args: dict[str, object]):
    provider = _normalize_provider(writer_args.get("provider"))
    if _use_service_expansion_writer(provider, writer_args):
        return load_service_writer(service_root, writer_args)

    executable = _select_cli_expansion_executable(provider)
    return CLIReviewWriter(
        executable=executable,
        model=writer_args.get("model") or None,
        timeout=_coerce_timeout(writer_args.get("timeout"), default=300),
    )


def load_service_writer(service_root: Path | None, writer_args: dict[str, object]):
    service_root = ensure_service_root(service_root)
    ensure_service_src_path(service_root)
    from co_researcher_service.services.review_writer import get_review_writer

    return get_review_writer(
        writer_args.get("provider"),
        model=writer_args.get("model"),
        base_url=writer_args.get("base_url"),
        api_key=writer_args.get("api_key"),
        temperature=writer_args.get("temperature"),
        timeout=writer_args.get("timeout"),
    )


def load_expansion_contract() -> str:
    if EXPANSION_CONTRACT_PATH.exists():
        return EXPANSION_CONTRACT_PATH.read_text(encoding="utf-8")
    return DEFAULT_EXPANSION_CONTRACT


def detect_knowledge_base_root() -> Path | None:
    env_root = os.environ.get("KB_ROOT")
    candidates = []
    if env_root:
        candidates.append(Path(env_root).expanduser())
    candidates.append(DEFAULT_KB_ROOT)
    repo_sibling = Path(__file__).resolve().parents[1].parent / "knowledge-base"
    candidates.append(repo_sibling)
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def load_creel_pack_screening(
    *,
    knowledge_base_root: Path | None,
    chapter_title: str,
    chapter_brief: str | None,
    sections: list[SectionBlock],
) -> str | None:
    if knowledge_base_root is None:
        return None

    pack_root = knowledge_base_root / "packs" / CREEL_PACK_NAME
    note_path = knowledge_base_root / CREEL_PACK_NOTE_PATH
    books_path = knowledge_base_root / CREEL_PACK_BOOKS_PATH
    if not pack_root.exists():
        return None

    terms = collect_screening_terms(
        chapter_title,
        chapter_brief or "",
        " ".join(section.title for section in sections if section.level > 0),
        " ".join(section.body for section in sections if section.level > 0),
    )

    note_excerpt = extract_screening_note_excerpt(note_path)
    title_matches = extract_books_title_blocks(books_path, terms)

    blocks: list[str] = []
    if note_excerpt:
        blocks.append("Creel pack manuscript screening:\n" + note_excerpt)
    if title_matches:
        blocks.append("Creel pack literature cues:\n" + "\n".join(f"- {block}" for block in title_matches))

    return "\n\n".join(blocks) if blocks else None


def collect_screening_terms(*parts: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for raw in re.findall(r"[A-Za-z][A-Za-z0-9'-]+", part.lower()):
            word = raw.strip("-'")
            if len(word) < 4 or word in SCREENING_STOPWORDS:
                continue
            if word in seen:
                continue
            seen.add(word)
            terms.append(word)
    return terms


def extract_screening_note_excerpt(note_path: Path) -> str | None:
    if not note_path.exists():
        return None

    wanted_headings = SCREENING_SECTION_HEADINGS
    blocks: list[str] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    def flush_current() -> None:
        if current_heading not in wanted_headings or not current_lines:
            return
        block = "\n".join(current_lines).strip()
        if not block:
            return
        blocks.append(block)

    for line in note_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            flush_current()
            current_heading = line.lstrip("#").strip()
            current_lines = [line]
            continue
        if current_heading in wanted_headings:
            current_lines.append(line)

    flush_current()
    if not blocks:
        return None
    return "\n\n".join(blocks)


def extract_books_title_blocks(books_path: Path, terms: list[str], *, max_blocks: int = 8) -> list[str]:
    if not books_path.exists() or not terms:
        return []

    lines = books_path.read_text(encoding="utf-8").splitlines()
    blocks: list[str] = []
    seen: set[str] = set()
    lowered_terms = [term.lower() for term in terms]

    for index, line in enumerate(lines):
        if not line.lstrip().startswith("title:"):
            continue
        title_line = line.lower()
        if not any(term in title_line for term in lowered_terms):
            continue
        start = index - 1 if index > 0 and lines[index - 1].lstrip().startswith("- id:") else index
        end = min(len(lines), index + 4)
        block = "\n".join(lines[start:end]).strip()
        if not block or block in seen:
            continue
        seen.add(block)
        blocks.append(block)
        if len(blocks) >= max_blocks:
            break

    return blocks


def _pick_brief_text(section_title: str, brief_sections: list[SectionBlock], fallback: str | None) -> str | None:
    if not brief_sections:
        return fallback
    target = _normalize_title(section_title)
    for brief_section in brief_sections:
        if brief_section.level == 0:
            continue
        if _normalize_title(brief_section.title) == target:
            return brief_section.body.strip() or fallback
    return fallback


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _normalize_provider(value: object) -> str:
    return str(value).strip().lower() if value is not None else ""


def _use_service_expansion_writer(provider: str, writer_args: dict[str, object]) -> bool:
    if provider in SERVICE_EXPANSION_PROVIDERS:
        return True
    if provider in CLI_EXPANSION_PROVIDERS or not provider:
        return False
    if writer_args.get("base_url") or writer_args.get("api_key"):
        return True
    return False


def _select_cli_expansion_executable(provider: str) -> str:
    if provider == "gemini":
        if shutil.which("gemini"):
            return "gemini"
        if shutil.which("agy"):
            return "agy"
        raise RuntimeError("No Gemini CLI executable found on PATH")

    if provider == "agy":
        if shutil.which("agy"):
            return "agy"
        if shutil.which("gemini"):
            return "gemini"
        raise RuntimeError("No agy or Gemini CLI executable found on PATH")

    if shutil.which("gemini"):
        return "gemini"
    if shutil.which("agy"):
        return "agy"
    raise RuntimeError("No agy or Gemini CLI executable found on PATH")


def resolve_cli_executable(name: str) -> str:
    resolved = shutil.which(name)
    if resolved:
        return name
    raise RuntimeError(f"{name} CLI is not available on PATH")


def _coerce_timeout(value: object, *, default: int) -> int:
    if value is None:
        return default
    return int(value)


def _writer_cli_args(writer_args: dict[str, object]) -> list[str]:
    mapping = (
        ("provider", "--writer"),
        ("model", "--writer-model"),
        ("base_url", "--writer-base-url"),
        ("api_key", "--writer-api-key"),
        ("temperature", "--writer-temperature"),
        ("timeout", "--writer-timeout"),
    )
    args: list[str] = []
    for key, flag in mapping:
        value = writer_args.get(key)
        if value is None:
            continue
        args.extend([flag, str(value)])
    return args


def detect_service_root() -> Path | None:
    repo_root = Path(__file__).resolve().parents[1]
    candidate = repo_root.parent / "research-bench" / "co-researcher-service"
    if candidate.exists() and (candidate / "src").exists():
        return candidate
    return None


def ensure_service_root(service_root: Path | None) -> Path:
    if service_root is None:
        discovered = detect_service_root()
        if discovered is None:
            raise RuntimeError("co-researcher-service checkout not found; provide --service-root")
        return discovered
    return service_root


def ensure_service_src_path(service_root: Path) -> None:
    service_src = service_root / "src"
    if str(service_src) not in sys.path:
        sys.path.insert(0, str(service_src))


def detect_service_python(service_root: Path) -> Path:
    for candidate in (
        service_root / ".venv" / "bin" / "python",
        service_root / ".venv" / "bin" / "python3",
    ):
        if candidate.exists():
            return candidate
    return Path(sys.executable)


def format_command(command: list[str]) -> str:
    return " ".join(shlex_quote(part) for part in command)


def shlex_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)


if __name__ == "__main__":
    raise SystemExit(main())
