# modern-creel-surveys

Planning and documentation workspace for a methods-first book companion to the `tidycreel` R package.

## What this repo is for

This repository is the architectural and planning home for a book titled:

**Modern Creel Survey Analysis in R**  
*Design, estimation, diagnostics, and reporting with `tidycreel`*

The goal is to teach the methods and workflow behind creel survey analysis, not to serve as a package manual.

## Repository layout

- `.ai/`: stable architecture notes and handoffs
- `.planning/`: active roadmap, chapter outline, and current state
- `chapters/`: Quarto chapter stubs for the book source
- `index.qmd`: book landing page
- `preface.qmd`: introductory front matter
- `_quarto.yml`: Quarto book configuration

## Working principles

- Methods first, software second
- Explicit assumptions over hidden defaults
- Relational data model over one-flat-spreadsheet thinking
- Honest support status for package features
- Reproducible, reviewable examples

## Current status

The repo now has:

- a stable architecture brief
- a chapter-level roadmap
- a Quarto book scaffold
- a README describing how the pieces fit together

## Next steps

1. Add chapter content incrementally, starting with the foundations.
2. Decide which examples should be synthetic versus real data.
3. Fill in the `tidycreel` support-status notes as the package shape becomes clearer.

## Book rewrite adapter

This repo now includes a small book-local adapter prototype for handing `.qmd`
chapters off to `co-researcher-service` while preserving Quarto structure.

Example dry run:

```bash
python3 scripts/book_rewrite_adapter.py chapters/01-why-creel-surveys-matter.qmd \
  --dry-run \
  --output /tmp/why-creel-surveys.rewritten.qmd
```

If the sibling `research-bench/co-researcher-service` checkout is present, the
adapter will try to use it automatically for rewrite runs unless you provide a
custom `--rewrite-command`.

Convenience `just` commands:

```bash
just rewrite-chapter-dry-run chapters/01-why-creel-surveys-matter.qmd
just rewrite-chapter-openrouter chapters/02-estimands-units-and-domains.qmd --output /tmp/estimands.qmd
just rewrite-chapters-dry-run chapters/01-why-creel-surveys-matter.qmd chapters/02-estimands-units-and-domains.qmd --output-dir /tmp/creel-drafts
just rewrite-chapters-openrouter chapters/01-why-creel-surveys-matter.qmd chapters/02-estimands-units-and-domains.qmd --output-dir /tmp/creel-drafts
just rewrite-foundations-dry-run --output-dir /tmp/creel-foundations
just rewrite-foundations-openrouter --output-dir /tmp/creel-foundations
just expand-chapter-gemini chapters/01-why-creel-surveys-matter.qmd --output /tmp/why-creel-expand.qmd
just expand-chapters-gemini chapters/01-why-creel-surveys-matter.qmd chapters/02-estimands-units-and-domains.qmd --output-dir /tmp/creel-expand
just expand-foundations-gemini --output-dir /tmp/creel-foundations-expand
```

For freeform expansion, the adapter uses the local `.ai/expansion-contract.md`
prompt contract and runs a draft pass followed by a polish pass by default.
These expansion recipes now prefer the installed `gemini` CLI and fall back to
`agy` if needed, so they use your CLI login/session instead of the OpenRouter
API path. They use the CLI's configured default model unless you pass an
explicit `--writer-model` override. You can pass `--brief path/to/brief.md` to
expand from a chapter brief or outline file instead of only the Quarto chapter
text, and `--no-polish` if you want to keep only the draft pass.

The expansion path now applies a conservative Quarto formatting cleanup before
writing the final draft. If you want to run that step separately, use
`python3 scripts/quarto_cleanup.py path/to/file.qmd --validate-render` to write
a cleaned sibling file and verify it with Quarto render. When the cleaned draft
contains `[AUTHOR YEAR]` placeholders, the cleanup step also writes a paired
`*_citation_suggestions.md` sidecar by calling the sibling
`co-researcher-service` workflow.
