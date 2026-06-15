from __future__ import annotations

from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import quarto_cleanup as cleanup  # noqa: E402


def test_cleanup_qmd_text_inserts_blank_lines_between_blocks():
    text = """---
title: "Test"
---
## One
Paragraph
- item
```r
1
```
## Two
"""

    cleaned = cleanup.cleanup_qmd_text(text)

    assert cleaned == """---
title: "Test"
---
## One

Paragraph

- item

```r
1
```

## Two
"""


def test_main_writes_citation_suggestions_sidecar(tmp_path, monkeypatch):
    input_path = tmp_path / "chapter.qmd"
    output_path = tmp_path / "chapter.cleaned.qmd"
    input_path.write_text(
        """---
title: "Test"
---
## One

Paragraph with [AUTHOR YEAR].
""",
        encoding="utf-8",
    )

    calls: list[tuple[str, Path | None]] = []

    def fake_generate_citation_suggestions(
        draft_text: str,
        output_path: Path | None,
        *,
        write_output: bool = True,
    ):
        calls.append((draft_text, output_path))
        return output_path.with_name(f"{output_path.stem}_citation_suggestions.md") if output_path else None

    monkeypatch.setattr(cleanup, "generate_citation_suggestions", fake_generate_citation_suggestions)
    monkeypatch.setattr(cleanup, "validate_render", lambda path: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["quarto_cleanup.py", str(input_path), "--output", str(output_path)],
    )

    assert cleanup.main() == 0

    assert calls
    assert calls[0][1] == output_path
    assert output_path.exists()
