from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import book_rewrite_adapter as adapter  # noqa: E402


def test_select_cli_expansion_executable_prefers_gemini(monkeypatch):
    monkeypatch.setattr(adapter.shutil, "which", lambda name: f"/usr/local/bin/{name}" if name in {"agy", "gemini"} else None)

    assert adapter._select_cli_expansion_executable("") == "gemini"


def test_cli_review_writer_builds_agy_prompt_argument(monkeypatch):
    monkeypatch.setattr(adapter.shutil, "which", lambda name: f"/usr/local/bin/{name}" if name == "agy" else None)

    writer = adapter.CLIReviewWriter(executable="agy", model="test-model")

    assert writer._build_command("Expand this section.") == [
        "agy",
        "--print",
        "Expand this section.",
        "--model",
        "test-model",
    ]


def test_cli_review_writer_builds_gemini_prompt_argument(monkeypatch):
    monkeypatch.setattr(adapter.shutil, "which", lambda name: f"/usr/local/bin/{name}" if name == "gemini" else None)

    writer = adapter.CLIReviewWriter(executable="gemini", model="test-model")

    assert writer._build_command("Expand this section.") == [
        "gemini",
        "--model",
        "test-model",
        "--prompt",
        "Expand this section.",
    ]


def test_load_expansion_writer_uses_cli_when_provider_is_missing(monkeypatch):
    monkeypatch.setattr(adapter.shutil, "which", lambda name: f"/usr/local/bin/{name}" if name in {"agy", "gemini"} else None)

    writer = adapter.load_expansion_writer(
        None,
        {
            "provider": None,
            "timeout": 42,
        },
    )

    assert isinstance(writer, adapter.CLIReviewWriter)
    assert writer.executable == "gemini"
    assert writer.model is None
    assert writer.timeout == 42


def test_load_expansion_writer_uses_service_for_explicit_api_provider(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(adapter, "load_service_writer", lambda service_root, writer_args: sentinel)

    writer = adapter.load_expansion_writer(
        Path("/tmp/service-root"),
        {
            "provider": "openai-compatible",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "token",
        },
    )

    assert writer is sentinel


def test_load_creel_pack_screening_uses_pack_notes_and_titles(tmp_path):
    kb_root = tmp_path / "knowledge-base"
    note_path = kb_root / "packs" / "creel_surveys" / "notes"
    note_path.mkdir(parents=True)
    (note_path / "scientific-manuscript-characteristics.md").write_text(
        """# Scientific Manuscript Characteristics

## Book Chapter

- The chapter can devote more space to definitions, context, and practical guidance.

## Working Rule of Thumb

- What was the question?
- How was it answered?
- What should we believe because of the answer?
""",
        encoding="utf-8",
    )

    books_path = kb_root / "packs" / "creel_surveys" / "config"
    books_path.mkdir(parents=True)
    (books_path / "books.yaml").write_text(
        """books:
- id: example1
  title: Bias
  authors: Example
  year: 2000
- id: example2
  title: Sampling
  authors: Example
  year: 2001
""",
        encoding="utf-8",
    )

    screening = adapter.load_creel_pack_screening(
        knowledge_base_root=kb_root,
        chapter_title="Bias and Failure Modes",
        chapter_brief=None,
        sections=[
            adapter.SectionBlock(level=1, title="Purpose", preface="", body="Bias and coverage sampling", protected_blocks=[]),
        ],
    )

    assert screening is not None
    assert "Creel pack manuscript screening" in screening
    assert "What was the question?" in screening
    assert "title: Bias" in screening
    assert "title: Sampling" in screening


def test_main_emits_citation_suggestions_sidecar(tmp_path, monkeypatch):
    input_path = tmp_path / "chapter.qmd"
    output_path = tmp_path / "chapter.cleaned.qmd"
    input_path.write_text("## One\n\nNotes with [AUTHOR YEAR].\n", encoding="utf-8")

    def fake_expand_sections(*args, **kwargs):
        return [
            adapter.SectionBlock(
                level=1,
                title="One",
                preface="",
                body="Expanded prose with [AUTHOR YEAR].",
                protected_blocks=[],
            )
        ]

    calls: list[tuple[str, Path | None]] = []

    def fake_generate_citation_suggestions(
        draft_text: str,
        output_path: Path | None,
        *,
        write_output: bool = True,
    ):
        calls.append((draft_text, output_path))
        return output_path.with_name(f"{output_path.stem}_citation_suggestions.md") if output_path else None

    monkeypatch.setattr(adapter, "expand_sections", fake_expand_sections)
    monkeypatch.setattr(adapter, "cleanup_qmd_text", lambda text: text)
    monkeypatch.setattr(adapter, "generate_citation_suggestions", fake_generate_citation_suggestions)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "book_rewrite_adapter.py",
            str(input_path),
            "--mode",
            "expand",
            "--output",
            str(output_path),
        ],
    )

    assert adapter.main() == 0

    assert calls
    assert calls[0][1] == output_path
    assert output_path.exists()
