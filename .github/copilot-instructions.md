# Critical Development Guidelines

## Commands (Python 3.14+ required)
- **ALWAYS use `uv run` prefix**: `uv run pytest`, `uv run ruff check .`, `uv run ruff format .`
- Never use pip/poetry or activate virtualenvs - uv handles everything
- `uv_build` is the build backend (not setuptools/poetry)

## Non-Negotiable Code Patterns

### Every Python File Must Have
```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Import types here to avoid circular deps
```

### Dataclasses Are Always Frozen
```python
@dataclass(frozen=True)  # Never mutable
class RedditUrlInfo:
    kind: RedditKind
    original_url: str
```

### Ruff Has ALL Rules Enabled
- `lint.select = ["ALL"]` with `unsafe-fixes = true` in pyproject.toml
- Google-style docstrings required (triple quotes, Args/Returns sections)
- Single-line imports enforced: `from typing import TYPE_CHECKING` (one import per line)
- Tests exempt from S101 (assert), D103 (docstrings), PLR2004 (magic values)
- 30+ rules ignored (see pyproject.toml) - mostly formatter conflicts (COM812, ISC001, etc.)

## Reddit Scraping Rules (Non-Obvious)

### Always Use old.reddit.com
- Modern Reddit has complex React-based HTML - old.reddit.com is simpler to parse
- URLs like `https://reddit.com/r/foo/...` won't work for scraping

### ID Normalization is Critical
```python
post_id.lower()  # IDs are case-insensitive but must be stored lowercase
comment_id.lower()
```

### HTTP Client Pattern
```python
# ALL downloads go through this - uses Chrome 137 impersonation to bypass bot detection
from webscrapers import download_page
html = await download_page("https://old.reddit.com/...")
```

### URL Parsing Architecture
1. Parse any Reddit URL → `RedditUrlInfo` (contains kind, IDs, context)
2. Download HTML via `download_page()` using old.reddit.com
3. Parse HTML with selectolax → `RedditPostData` / `RedditCommentData`

## Testing Patterns
- Function names describe behavior: `test_parses_standard_post_url()` not `test_url_parsing()`
- Assert directly on dataclass fields: `assert info.post_id == "npm69h"`
- Exception testing: `with pytest.raises(RedditScraperError):`
- Real Reddit HTML fixture: `reddit_post_example.html` (excluded from djlint linting via pyproject.toml)

## Known Incomplete Work
- `parse_reddit_post_html()` raises NotImplementedError - needs selectolax implementation
- `scrape_frontpage()` and `scrape_user_profile()` are empty stubs
- `build_comment_tree()` defined but unused (for future comment thread reconstruction)
