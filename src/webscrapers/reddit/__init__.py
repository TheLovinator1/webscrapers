from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING
from typing import Literal
from urllib.parse import ParseResult
from urllib.parse import urlparse

from pydantic import BaseModel
from selectolax.parser import HTMLParser
from selectolax.parser import Node

from webscrapers import download_page

if TYPE_CHECKING:
    from collections.abc import Callable

logger: logging.Logger = logging.getLogger(__name__)


class RedditScraperError(Exception):
    """Custom exception for Reddit scraper errors."""


_POST_ID_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9]{5,8}$")
_COMMENT_ID_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9]{6,10}$")
SHORTLINK_HOSTS: set[str] = {"redd.it", "www.redd.it"}
MIN_SUBREDDIT_SEGMENTS = 2
MIN_POST_SEGMENTS = 4
MIN_COMMENT_SEGMENTS = 6


RedditKind = Literal[
    "frontpage",
    "popular",
    "all",
    "subreddit",
    "user",
    "post",
    "comment",
]


class RedditUrlInfo(BaseModel):
    """Parsed details from a Reddit URL.

    Represents parsed components of a Reddit URL, including its original link,
    the target subreddit or user, and identifiers for posts or comments. Provides
    a convenience property to determine whether the URL references a specific post
    or comment.

    Attributes:
        kind: The type of Reddit URL (e.g., 'post', 'comment', 'user', etc.).
        original_url: The original Reddit URL that was parsed.
        subreddit: The subreddit name if applicable.
        username: The Reddit username if applicable.
        post_id: The post ID if applicable.
        comment_id: The comment ID if applicable.
    """

    class Config:
        frozen = True  # frozen, preventing attribute modification

    kind: RedditKind
    """The type of Reddit URL (e.g., 'post', 'comment', 'user', etc.)."""

    original_url: str
    """The original Reddit URL that was parsed."""

    subreddit: str | None = None
    """The subreddit name if applicable."""

    username: str | None = None
    """The Reddit username if applicable."""

    post_id: str | None = None
    """The post ID if applicable."""

    comment_id: str | None = None
    """The comment ID if applicable."""

    @property
    def has_post(self) -> bool:
        """Return True if the URL points to a post or comment."""
        return self.post_id is not None


class RedditPostData(BaseModel):
    """Parsed data for a Reddit post page.

    Attributes:
        post_id: Post ID.
        title: Post title.
        author: Post author.
        subreddit: Subreddit name.
        score: Post score.
        url: Post URL.
        permalink: Post permalink.
        content_html: Post content HTML.
        date_posted: Date posted.
        num_comments: Number of comments.
        is_nsfw: NSFW flag.
        is_spoiler: Spoiler flag.
        domain: Post domain.
        flair: Post flair.
        comments: Tuple of RedditCommentData.
    """

    class Config:
        frozen = True

    post_id: str | None = None
    title: str | None = None
    author: str | None = None
    subreddit: str | None = None
    score: int | None = None
    url: str | None = None
    permalink: str | None = None
    content_html: str | None = None
    date_posted: datetime | None = None
    num_comments: int | None = None
    is_nsfw: bool = False
    is_spoiler: bool = False
    domain: str | None = None
    flair: str | None = None
    comments: tuple[RedditCommentData, ...] = ()


class RedditCommentData(BaseModel):
    """Parsed data for a Reddit comment.

    Represents a single comment with full thread reconstruction support. Comments
    can be linked by parent_id to build trees, or stored flat for archival.

    Attributes:
        comment_id: Unique Reddit comment ID (e.g., 'a1b2c3d').
        post_id: ID of the post this comment belongs to.
        parent_id: ID of the parent comment (None if direct reply to post).
        author: Username of the comment author.
        date_posted: Timestamp when the comment was posted.
        content_html: Raw HTML content of the comment.
        content_markdown: Markdown-formatted content of the comment.
        content_text: Plain text version of the comment (no HTML/Markdown).
        score: Current vote score (upvotes - downvotes).
        edited: False if not edited, datetime if edited (contains edit timestamp).
        deleted: True if comment was deleted by the author.
        removed: True if comment was removed by moderators/Reddit.
        is_submitter: True if the comment author is the original post creator.
        distinguished: Distinguishment type: 'moderator', 'admin', 'special', or None.
        stickied: True if the comment is stickied (pinned) by a moderator.
        permalink: Full permalink URL for this comment.
        depth: Nesting depth in the comment thread (0 = top-level).
        children: Child comments (replies to this comment).
            Use build_comment_tree() for trees.
    """

    class Config:
        frozen = True

    comment_id: str | None = None
    """Unique Reddit comment ID (e.g., 'a1b2c3d')."""

    post_id: str | None = None
    """ID of the post this comment belongs to."""

    parent_id: str | None = None
    """ID of the parent comment (None if direct reply to post)."""

    author: str | None = None
    """Username of the comment author."""

    date_posted: datetime | None = None
    """Timestamp when the comment was posted."""

    content_html: str | None = None
    """Raw HTML content of the comment."""

    content_markdown: str | None = None
    """Markdown-formatted content of the comment."""

    content_text: str | None = None
    """Plain text version of the comment (no HTML/Markdown)."""

    score: int | None = None
    """Current vote score (upvotes - downvotes)."""

    edited: bool | datetime | None = None
    """False if not edited, datetime if edited (contains edit timestamp)."""

    deleted: bool = False
    """True if comment was deleted by the author."""

    removed: bool = False
    """True if comment was removed by moderators/Reddit."""

    is_submitter: bool = False
    """True if the comment author is the original post creator."""

    distinguished: str | None = None
    """Distinguishment type: 'moderator', 'admin', 'special', or None."""

    stickied: bool = False
    """True if the comment is stickied (pinned) by a moderator."""

    permalink: str | None = None
    """Full permalink URL for this comment."""

    depth: int | None = None
    """Nesting depth in the comment thread (0 = top-level)."""

    children: tuple[RedditCommentData, ...] = ()
    """Child comments (replies to this comment). Use build_comment_tree() for trees."""


def _normalize_netloc(netloc: str) -> str:
    return netloc.lower().split(":", maxsplit=1)[0]


def _split_path(path: str) -> list[str]:
    return [segment for segment in path.split("/") if segment]


def _parse_reddit_domain(parsed_netloc: str) -> bool:
    netloc: str = _normalize_netloc(parsed_netloc)
    if netloc in SHORTLINK_HOSTS:
        return True
    return netloc == "reddit.com" or netloc.endswith(".reddit.com")


def _parse_shortlink(
    netloc: str,
    segments: list[str],
    url: str,
) -> RedditUrlInfo | None:
    if netloc not in SHORTLINK_HOSTS:
        return None

    slug: str = segments[0] if segments else ""
    if not _POST_ID_RE.match(slug):
        msg = "Shortlink missing a valid post ID"
        raise RedditScraperError(msg)

    return RedditUrlInfo(
        kind="post",
        post_id=slug.lower(),
        original_url=url,
    )


def _parse_frontpage(
    _netloc: str,
    segments: list[str],
    url: str,
) -> RedditUrlInfo | None:
    if segments:
        return None

    return RedditUrlInfo(kind="frontpage", original_url=url)


def _parse_subreddit_path(
    _netloc: str,
    segments: list[str],
    url: str,
) -> RedditUrlInfo | None:
    if len(segments) < MIN_SUBREDDIT_SEGMENTS or segments[0] != "r":
        return None

    subreddit: str = segments[1]

    if subreddit.lower() == "popular":
        return RedditUrlInfo(kind="popular", original_url=url)
    if subreddit.lower() == "all":
        return RedditUrlInfo(kind="all", original_url=url)

    if len(segments) >= MIN_POST_SEGMENTS and segments[2] == "comments":
        post_id: str = segments[3]
        if not _POST_ID_RE.match(post_id):
            msg = "URL contains an invalid post ID"
            raise RedditScraperError(msg)

        comment_id = None
        if len(segments) >= MIN_COMMENT_SEGMENTS:
            candidate: str = segments[5]
            if _COMMENT_ID_RE.match(candidate):
                comment_id = candidate.lower()

        kind: RedditKind = "comment" if comment_id else "post"

        return RedditUrlInfo(
            kind=kind,
            original_url=url,
            subreddit=subreddit,
            post_id=post_id.lower(),
            comment_id=comment_id,
        )

    return RedditUrlInfo(
        kind="subreddit",
        original_url=url,
        subreddit=subreddit,
    )


def _parse_user_path(
    _netloc: str,
    segments: list[str],
    url: str,
) -> RedditUrlInfo | None:
    if len(segments) < MIN_SUBREDDIT_SEGMENTS or segments[0] not in {"user", "u"}:
        return None

    username: str = segments[1]
    return RedditUrlInfo(kind="user", original_url=url, username=username)


def get_reddit_id_from_url(url: str) -> RedditUrlInfo:
    """Parse Reddit URL details.

    Args:
        url: Any Reddit URL (posts, comments, users, subreddits,
            frontpage, or shortlinks)

    Returns:
        RedditUrlInfo containing kind, optional IDs, and context fields.

    Raises:
        RedditScraperError: If the URL is empty, non-Reddit, or unrecognized.
    """
    if not url or not url.strip():
        msg = "A non-empty Reddit URL is required"
        raise RedditScraperError(msg)

    parsed: ParseResult = urlparse(url.strip())

    if not _parse_reddit_domain(parsed.netloc):
        msg = "URL does not belong to reddit"
        raise RedditScraperError(msg)

    netloc: str = _normalize_netloc(parsed.netloc)
    segments: list[str] = _split_path(parsed.path)

    parsers: tuple[
        Callable[..., RedditUrlInfo | None],
        Callable[..., RedditUrlInfo | None],
        Callable[..., RedditUrlInfo | None],
        Callable[..., RedditUrlInfo | None],
    ] = (
        _parse_shortlink,
        _parse_frontpage,
        _parse_subreddit_path,
        _parse_user_path,
    )

    for parser in parsers:
        info: RedditUrlInfo | None = parser(netloc, segments, url)
        if info:
            return info

    msg = "URL does not match a supported Reddit pattern"
    raise RedditScraperError(msg)


def build_comment_tree(
    comments: list[RedditCommentData],
) -> dict[str | None, list[RedditCommentData]]:
    """Build a tree structure from a flat list of comments using parent_id.

    Maps parent comment IDs to their direct children. Use this to reconstruct
    the thread hierarchy when needed for display or traversal.

    Args:
        comments: Flat list of RedditCommentData objects with parent_id set.

    Returns:
        A dict mapping parent_id (or None for top-level) to list of children.
    """
    tree: dict[str | None, list[RedditCommentData]] = {}
    for comment in comments:
        parent: str | None = comment.parent_id
        if parent not in tree:
            tree[parent] = []
        tree[parent].append(comment)

    return tree


def _normalize_text(text: str | None) -> str | None:
    """Normalize whitespace in extracted text.

    Args:
        text: Text to normalize, possibly containing newlines and excess whitespace.

    Returns:
        Text with normalized whitespace, or None if input is None.
    """
    if text is None:
        return None

    return " ".join(text.split())


def _extract_fullname_id(fullname: str | None) -> str | None:
    """Extract the ID portion from a Reddit fullname (e.g., 't3_abc123' -> 'abc123').

    Args:
        fullname: Reddit fullname like 't3_abc123' or 't1_xyz789'.

    Returns:
        The ID portion without the type prefix, or None if invalid.
    """
    if not fullname:
        return None

    parts: list[str] = fullname.split("_", maxsplit=1)

    if len(parts) == 2:  # noqa: PLR2004
        return parts[1].lower()

    return None


def _parse_timestamp(time_element: Node | None) -> datetime | None:
    """Parse datetime from a <time> element's datetime attribute.

    Args:
        time_element: A selectolax Node representing a <time> element.

    Returns:
        Parsed datetime object or None if parsing fails.
    """
    if time_element is None:
        return None

    dt_str: str | None = time_element.attributes.get("datetime")
    if not dt_str:
        return None

    try:
        return datetime.fromisoformat(dt_str)
    except ValueError:
        return None


def _parse_score(score_element: Node | None) -> int | None:
    """Parse score from a score element's title attribute.

    Args:
        score_element: A selectolax Node representing a score span.

    Returns:
        Integer score or None if parsing fails.
    """
    if score_element is None:
        return None

    title: str | None = score_element.attributes.get("title")
    if title:
        try:
            return int(title)
        except ValueError:
            pass

    return None


class _CommentParseContext(BaseModel):
    """Context data extracted from a comment node for building RedditCommentData."""

    comment_id: str | None
    author: str | None
    score: int | None
    date_posted: datetime | None
    content_html: str | None
    content_text: str | None
    permalink: str | None
    parent_id: str | None
    is_deleted: bool
    is_removed: bool
    is_submitter: bool
    distinguished: str | None
    stickied: bool


def _extract_comment_author(entry: Node, *, is_deleted: bool) -> str | None:
    """Extract author name from a comment entry node.

    Args:
        entry: The entry div of the comment.
        is_deleted: Whether the comment is marked as deleted.

    Returns:
        Author username or '[deleted]' if deleted.
    """
    author_elem: Node | None = entry.css_first("a.author")
    if author_elem:
        return author_elem.text(strip=True)

    # Check for deleted author indicated by span with [deleted]
    tagline: Node | None = entry.css_first("p.tagline")
    if tagline:
        tagline_text: str = tagline.text()
        if "[deleted]" in tagline_text:
            return "[deleted]"

    if is_deleted:
        return "[deleted]"

    return None


def _extract_comment_content(entry: Node) -> tuple[str | None, str | None, bool, bool]:
    """Extract content from a comment entry node.

    Args:
        entry: The entry div of the comment.

    Returns:
        Tuple of (content_html, content_text, is_deleted, is_removed).
    """
    content_div: Node | None = entry.css_first("div.usertext-body div.md")
    if not content_div:
        return None, None, False, False

    content_html: str | None = content_div.html
    content_text: str = content_div.text(strip=True)

    is_removed: bool = content_text == "[removed]"
    is_deleted: bool = content_text == "[deleted]"

    return content_html, content_text, is_deleted, is_removed


def _extract_comment_metadata(
    node: Node,
    entry: Node,
) -> tuple[str | None, str | None, bool]:
    """Extract metadata from a comment node.

    Args:
        node: The thing.comment node.
        entry: The entry div of the comment.

    Returns:
        Tuple of (distinguished, permalink, stickied).
    """
    node_class: str = node.attributes.get("class") or ""

    distinguished: str | None = None
    if "moderator" in node_class:
        distinguished = "moderator"
    elif "admin" in node_class:
        distinguished = "admin"

    stickied: bool = "stickied" in node_class

    permalink_elem: Node | None = entry.css_first("a[data-event-action='permalink']")
    permalink: str | None = (
        permalink_elem.attributes.get("href") if permalink_elem else None
    )

    return distinguished, permalink, stickied


def _extract_parent_id(entry: Node) -> str | None:
    """Extract parent comment ID from a comment entry.

    Args:
        entry: The entry div of the comment.

    Returns:
        Parent comment ID or None if top-level comment.
    """
    parent_link: Node | None = entry.css_first("a[data-event-action='parent']")
    if parent_link:
        href: str | None = parent_link.attributes.get("href")
        if href and href.startswith("#"):
            return href[1:]

    return None


def _build_comment_context(node: Node) -> _CommentParseContext | None:
    """Build comment context from a comment node.

    Args:
        node: The div.thing.comment node.

    Returns:
        _CommentParseContext or None if invalid.
    """
    fullname: str | None = node.attributes.get("data-fullname")
    comment_id: str | None = _extract_fullname_id(fullname)
    if not comment_id:
        return None

    node_class: str = node.attributes.get("class") or ""
    is_deleted_class: bool = "deleted" in node_class

    entry: Node | None = node.css_first("div.entry")
    if not entry:
        return None

    content_html, content_text, content_deleted, is_removed = _extract_comment_content(
        entry,
    )
    is_deleted: bool = is_deleted_class or content_deleted
    author: str | None = _extract_comment_author(entry, is_deleted=is_deleted)
    distinguished, permalink, stickied = _extract_comment_metadata(node, entry)

    return _CommentParseContext(
        comment_id=comment_id,
        author=author,
        score=_parse_score(entry.css_first("span.score.unvoted")),
        date_posted=_parse_timestamp(entry.css_first("time.live-timestamp")),
        content_html=content_html,
        content_text=content_text,
        permalink=permalink,
        parent_id=_extract_parent_id(entry),
        is_deleted=is_deleted,
        is_removed=is_removed,
        is_submitter="submitter" in node_class,
        distinguished=distinguished,
        stickied=stickied,
    )


def _parse_comment_node(
    node: Node,
    post_id: str | None,
    depth: int = 0,
) -> RedditCommentData | None:
    """Parse a single comment node from the HTML.

    Args:
        node: The div.thing.comment node to parse.
        post_id: The ID of the post this comment belongs to.
        depth: The nesting depth of this comment.

    Returns:
        RedditCommentData object or None if the node is not a valid comment.
    """
    if node.attributes.get("data-type") == "morechildren":
        return None

    ctx: _CommentParseContext | None = _build_comment_context(node)
    if ctx is None:
        return None

    children: list[RedditCommentData] = []
    child_container: Node | None = node.css_first("div.child div.sitetable")
    if child_container:
        for child_node in _get_direct_comment_children(child_container):
            child_comment: RedditCommentData | None = _parse_comment_node(
                node=child_node,
                post_id=post_id,
                depth=depth + 1,
            )
            if child_comment:
                children.append(child_comment)

    return RedditCommentData(
        comment_id=ctx.comment_id,
        post_id=post_id,
        parent_id=ctx.parent_id,
        author=ctx.author,
        date_posted=ctx.date_posted,
        content_html=ctx.content_html,
        content_text=ctx.content_text,
        score=ctx.score,
        deleted=ctx.is_deleted,
        removed=ctx.is_removed,
        is_submitter=ctx.is_submitter,
        distinguished=ctx.distinguished,
        stickied=ctx.stickied,
        permalink=ctx.permalink,
        depth=depth,
        children=tuple(children),
    )


class _PostParseContext(BaseModel):
    """Context data extracted from a post node for building RedditPostData."""

    post_id: str | None
    title: str | None
    author: str | None
    subreddit: str | None
    score: int | None
    url: str | None
    permalink: str | None
    content_html: str | None
    date_posted: datetime | None
    num_comments: int | None
    is_nsfw: bool
    is_spoiler: bool
    domain: str | None
    flair: str | None


def _extract_post_author(post_node: Node) -> str | None:
    """Extract author from a post node.

    Args:
        post_node: The div.thing.link node.

    Returns:
        Author username or '[deleted]'.
    """
    author_elem: Node | None = post_node.css_first("p.tagline a.author")
    if author_elem:
        return author_elem.text(strip=True)

    tagline: Node | None = post_node.css_first("p.tagline")
    if tagline and "[deleted]" in tagline.text():
        return "[deleted]"

    return None


def _extract_post_num_comments(post_node: Node) -> int | None:
    """Extract number of comments from a post node.

    Args:
        post_node: The div.thing.link node.

    Returns:
        Number of comments or None.
    """
    comments_count_str: str | None = post_node.attributes.get("data-comments-count")
    if comments_count_str:
        try:
            return int(comments_count_str)
        except ValueError:
            return None
    return None


def _build_post_context(post_node: Node) -> _PostParseContext:
    """Build post context from a post node.

    Args:
        post_node: The div.thing.link node.

    Returns:
        _PostParseContext with extracted data.
    """
    post_id: str | None = _extract_fullname_id(
        post_node.attributes.get("data-fullname")
    )
    title_elem: Node | None = post_node.css_first("a.title")
    flair_elem: Node | None = post_node.css_first("span.linkflairlabel")
    expando: Node | None = post_node.css_first("div.expando div.usertext-body div.md")

    title_text: str | None = title_elem.text(strip=True) if title_elem else None
    title: str | None = _normalize_text(title_text)

    return _PostParseContext(
        post_id=post_id,
        title=title,
        author=_extract_post_author(post_node),
        subreddit=post_node.attributes.get("data-subreddit"),
        score=_parse_score(post_node.css_first("div.score.unvoted")),
        url=post_node.attributes.get("data-url"),
        permalink=post_node.attributes.get("data-permalink"),
        content_html=expando.html if expando else None,
        date_posted=_parse_timestamp(post_node.css_first("time.live-timestamp")),
        num_comments=_extract_post_num_comments(post_node),
        is_nsfw=post_node.attributes.get("data-nsfw") == "true",
        is_spoiler=post_node.attributes.get("data-spoiler") == "true",
        domain=post_node.attributes.get("data-domain"),
        flair=flair_elem.text(strip=True) if flair_elem else None,
    )


def _get_direct_comment_children(container: Node) -> list[Node]:
    """Get direct comment children from a container node.

    Args:
        container: A sitetable container node.

    Returns:
        List of direct child comment nodes.
    """
    children: list[Node] = []
    for child in container.iter():
        if child.tag != "div":
            continue

        classes: str = child.attributes.get("class") or ""
        if "thing" in classes and "comment" in classes:
            children.append(child)

    return children


def parse_reddit_post_html(the_page: str) -> RedditPostData:
    """Parse Reddit post HTML and extract post metadata and comments.

    Args:
        the_page: Raw HTML content of a Reddit post page from old.reddit.com.

    Returns:
        RedditPostData containing extracted post information and comments.

    Raises:
        RedditScraperError: If the HTML cannot be parsed or required data is missing.
    """
    parser = HTMLParser(the_page)

    # Try original selector
    post_node: Node | None = parser.css_first("div.thing.link")
    # Try fallback selectors if not found
    if not post_node:
        # Try to find any div with class 'thing' and 'link' (in any order)
        for node in parser.css("div.thing"):
            classes: str = node.attributes.get("class") or ""
            if "link" in classes:
                post_node = node
                break

    if not post_node:
        # Debug: print first 1000 chars of HTML to help diagnose
        debug_snippet: str = the_page[:1000].replace("\n", " ")
        logger.debug(
            "[DEBUG] Could not find post element. HTML snippet: %s",
            debug_snippet,
        )
        msg = "Could not find post element in HTML"
        raise RedditScraperError(msg)

    ctx: _PostParseContext = _build_post_context(post_node)

    comments: list[RedditCommentData] = []
    comment_area: Node | None = parser.css_first(
        "div.commentarea div.sitetable.nestedlisting"
    )
    if comment_area:
        for comment_node in _get_direct_comment_children(comment_area):
            comment: RedditCommentData | None = _parse_comment_node(
                node=comment_node,
                post_id=ctx.post_id,
                depth=0,
            )
            if comment:
                comments.append(comment)

    return RedditPostData(
        post_id=ctx.post_id,
        title=ctx.title,
        author=ctx.author,
        subreddit=ctx.subreddit,
        score=ctx.score,
        url=ctx.url,
        permalink=ctx.permalink,
        content_html=ctx.content_html,
        date_posted=ctx.date_posted,
        num_comments=ctx.num_comments,
        is_nsfw=ctx.is_nsfw,
        is_spoiler=ctx.is_spoiler,
        domain=ctx.domain,
        flair=ctx.flair,
        comments=tuple(comments),
    )


async def scrape_post(
    post_url: str | None = None,
    post_id: str | None = None,
) -> RedditPostData:
    """Scrape a single Reddit post by URL or ID.

    If both post_url and post_id are provided, post_id takes precedence.

    Args:
        post_url: Full Reddit post URL
        post_id: Reddit post ID (e.g., '1az7z6a')

    Returns:
        RedditPostData containing the scraped post information and comments.

    Raises:
        RedditScraperError: If neither post_url nor post_id is provided
    """
    if not post_url and not post_id:
        msg = "Either post_url or post_id must be provided"
        raise RedditScraperError(msg)

    # Extract ID from URL if needed
    if not post_id:
        post_id = extract_post_id_from_url(post_url)

    # Download the HTML content of the post page
    the_page: str = await download_page(f"https://old.reddit.com/comments/{post_id}/")

    # Parse the HTML content to extract post details
    return parse_reddit_post_html(the_page)


def extract_post_id_from_url(post_url: str | None) -> str | None:
    """Extract Reddit post ID from a given URL.

    Args:
        post_url: Full Reddit post URL

    Raises:
        RedditScraperError: If the URL does not point to a valid Reddit post

    Returns:
        The extracted post ID if found, otherwise None.
    """
    post_id: str | None = None
    if post_url:
        info: RedditUrlInfo = get_reddit_id_from_url(post_url)
        if not info.post_id:
            msg = "Provided URL does not point to a Reddit post"
            raise RedditScraperError(msg)

        post_id = info.post_id
    return post_id


def scrape_frontpage(subreddit: str | None = None) -> None:
    """Scrape Reddit frontpage or specific subreddit."""


def scrape_user_profile(username: str) -> None:
    """Scrape a user's profile and posts."""
