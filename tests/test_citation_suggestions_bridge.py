from __future__ import annotations

from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import citation_suggestions_bridge as bridge  # noqa: E402


def test_generate_citation_suggestions_writes_sidecar(tmp_path, monkeypatch):
    service_root = tmp_path / "research-bench" / "co-researcher-service"
    service_src = service_root / "src" / "co_researcher_service"
    exporters_dir = service_src / "exporters"
    services_dir = service_src / "services"
    exporters_dir.mkdir(parents=True)
    services_dir.mkdir(parents=True)

    (service_src / "__init__.py").write_text("", encoding="utf-8")
    (exporters_dir / "__init__.py").write_text("", encoding="utf-8")
    (services_dir / "__init__.py").write_text("", encoding="utf-8")
    (exporters_dir / "citation_suggestions.py").write_text(
        """from __future__ import annotations


def render_citation_suggestions(draft_text, registry=None):
    assert "[AUTHOR YEAR]" in draft_text
    assert registry == {"source": "default"}
    return "suggestions body\\n"
""",
        encoding="utf-8",
    )
    (services_dir / "registry_factory.py").write_text(
        """from __future__ import annotations


def build_default_registry():
    return {"source": "default"}
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(bridge, "detect_service_root", lambda: service_root)
    output_path = tmp_path / "chapter.cleaned.qmd"

    suggestions_path = bridge.generate_citation_suggestions(
        "Paragraph with [AUTHOR YEAR].",
        output_path,
    )

    assert suggestions_path == tmp_path / "chapter.cleaned_citation_suggestions.md"
    assert suggestions_path.read_text(encoding="utf-8") == "suggestions body\n"


def test_generate_citation_suggestions_skips_when_no_placeholder(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "detect_service_root", lambda: None)

    assert bridge.generate_citation_suggestions("No placeholders here.", tmp_path / "chapter.qmd") is None
