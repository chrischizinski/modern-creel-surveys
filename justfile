set shell := ["bash", "-lc"]
python := "/opt/homebrew/bin/python3"

rewrite-chapter +ARGS:
    {{python}} scripts/book_rewrite_adapter.py {{ARGS}}

rewrite-chapter-openrouter +ARGS:
    {{python}} scripts/book_rewrite_adapter.py --service-root /Users/cchizinski2/Dev/research-bench/co-researcher-service --writer-provider openai-compatible --writer-base-url https://openrouter.ai/api/v1 --writer-model openai/gpt-oss-120b:free --writer-api-key "$OPENROUTER_API_KEY" --writer-timeout 300 {{ARGS}}

rewrite-chapter-dry-run +ARGS:
    {{python}} scripts/book_rewrite_adapter.py {{ARGS}} --dry-run

rewrite-chapters-openrouter +ARGS:
    {{python}} scripts/book_rewrite_batch.py --preset openrouter {{ARGS}}

rewrite-chapters-dry-run +ARGS:
    {{python}} scripts/book_rewrite_batch.py --preset dry-run {{ARGS}}

rewrite-foundations-openrouter +ARGS:
    {{python}} scripts/book_rewrite_batch.py --preset openrouter chapters/01-why-creel-surveys-matter.qmd chapters/02-estimands-units-and-domains.qmd chapters/03-design-based-logic-of-creel-estimation.qmd {{ARGS}}

rewrite-foundations-dry-run +ARGS:
    {{python}} scripts/book_rewrite_batch.py --preset dry-run chapters/01-why-creel-surveys-matter.qmd chapters/02-estimands-units-and-domains.qmd chapters/03-design-based-logic-of-creel-estimation.qmd {{ARGS}}

expand-chapter-gemini +ARGS:
    {{python}} scripts/book_rewrite_adapter.py --mode expand --writer-timeout 300 --polish-writer-provider agy {{ARGS}}

expand-chapters-gemini +ARGS:
    {{python}} scripts/book_rewrite_batch.py --mode expand --preset custom --writer-timeout 300 --polish-writer-provider agy {{ARGS}}

expand-chapters-dry-run +ARGS:
    {{python}} scripts/book_rewrite_batch.py --mode expand --preset dry-run {{ARGS}}

expand-foundations-gemini +ARGS:
    {{python}} scripts/book_rewrite_batch.py --mode expand --preset custom --writer-timeout 300 --polish-writer-provider agy chapters/01-why-creel-surveys-matter.qmd chapters/02-estimands-units-and-domains.qmd chapters/03-design-based-logic-of-creel-estimation.qmd {{ARGS}}

expand-foundations-dry-run +ARGS:
    {{python}} scripts/book_rewrite_batch.py --mode expand --preset dry-run chapters/01-why-creel-surveys-matter.qmd chapters/02-estimands-units-and-domains.qmd chapters/03-design-based-logic-of-creel-estimation.qmd {{ARGS}}
