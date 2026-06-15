"""Bridge from cleaned chapter drafts to co-researcher citation suggestions."""

from __future__ import annotations

from pathlib import Path
import sys


def generate_citation_suggestions(
    draft_text: str,
    output_path: Path | None,
    *,
    write_output: bool = True,
) -> Path | None:
    """Generate the paired citation-suggestions markdown file for a draft.

    Returns the written suggestions path, or None if no `[AUTHOR YEAR]`
    placeholders were found or the service could not generate suggestions.
    """
    if "[AUTHOR YEAR]" not in draft_text or output_path is None:
        return None

    service_root = detect_service_root()
    if service_root is None:
        return None

    ensure_service_src_path(service_root)
    from co_researcher_service.exporters.citation_suggestions import render_citation_suggestions

    registry = None
    try:
        from co_researcher_service.services.registry_factory import build_default_registry

        registry = build_default_registry()
    except Exception:
        registry = None

    suggestions = render_citation_suggestions(draft_text, registry=registry)
    if not suggestions:
        return None

    suggestions_path = output_path.with_name(f"{output_path.stem}_citation_suggestions.md")
    if write_output:
        suggestions_path.write_text(suggestions, encoding="utf-8")
    return suggestions_path


def detect_service_root() -> Path | None:
    repo_root = Path(__file__).resolve().parents[1]
    candidate = repo_root.parent / "research-bench" / "co-researcher-service"
    if candidate.exists() and (candidate / "src").exists():
        return candidate
    return None


def ensure_service_src_path(service_root: Path) -> None:
    service_src = service_root / "src"
    if str(service_src) not in sys.path:
        sys.path.insert(0, str(service_src))
