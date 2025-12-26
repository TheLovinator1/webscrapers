from pathlib import Path

import pytest

from webscrapers.reddit import RedditScraperError
from webscrapers.reddit import get_reddit_id_from_url
from webscrapers.reddit import parse_reddit_post_html


@pytest.fixture
def example_post_html() -> str:
    """Load the example Reddit post HTML fixture.

    Returns:
        The HTML content of the example Reddit post.
    """
    fixture_path = Path(__file__).parent / "reddit_post_example.html"
    return fixture_path.read_text(encoding="utf-8")


def test_parses_standard_post_url() -> None:
    url = (
        "https://old.reddit.com/r/homelab/comments/"
        "g76orz/i_bought_a_nintendo_switch_but_it_looks_a_little/"
    )
    info = get_reddit_id_from_url(url)

    assert info.kind == "post"
    assert info.post_id == "g76orz"
    assert info.subreddit == "homelab"
    assert info.comment_id is None


def test_parses_comment_permalink() -> None:
    url = (
        "https://old.reddit.com/r/nvidia/comments/npm69h/"
        "tech_support_and_question_megathread_june_2021/h1iloux/"
    )
    info = get_reddit_id_from_url(url)

    assert info.kind == "comment"
    assert info.post_id == "npm69h"
    assert info.comment_id == "h1iloux"
    assert info.subreddit == "nvidia"


def test_parses_shortlink() -> None:
    info = get_reddit_id_from_url("https://redd.it/npm69h")

    assert info.kind == "post"
    assert info.post_id == "npm69h"
    assert info.subreddit is None


def test_parses_user_profile_url() -> None:
    info = get_reddit_id_from_url("https://old.reddit.com/user/killyoy")

    assert info.kind == "user"
    assert info.username == "killyoy"


def test_parses_subreddit_root() -> None:
    info = get_reddit_id_from_url("https://old.reddit.com/r/nvidia/")

    assert info.kind == "subreddit"
    assert info.subreddit == "nvidia"


def test_parses_popular_and_all() -> None:
    popular = get_reddit_id_from_url("https://old.reddit.com/r/popular/")
    all_posts = get_reddit_id_from_url("https://old.reddit.com/r/all/")

    assert popular.kind == "popular"
    assert all_posts.kind == "all"


def test_parses_frontpage() -> None:
    info = get_reddit_id_from_url("https://old.reddit.com/")

    assert info.kind == "frontpage"


def test_raises_for_non_reddit_url() -> None:
    with pytest.raises(RedditScraperError):
        get_reddit_id_from_url("https://example.com/foo")


def test_raises_for_empty_url() -> None:
    with pytest.raises(RedditScraperError):
        get_reddit_id_from_url("   ")


# HTML Parsing Tests


def test_parses_post_metadata(example_post_html: str) -> None:
    post = parse_reddit_post_html(example_post_html)

    assert post.post_id == "1lqa2hj"
    expected_title = "Has Xbox Considered Laying One Person Off Instead Of Thousands"
    assert post.title == expected_title
    assert post.author == "[deleted]"
    assert post.subreddit == "Games"
    assert post.score == 8724
    assert post.url == "https://aftermath.site/xbox-layoffs-microsoft-phil-spencer"
    assert post.domain == "aftermath.site"
    assert post.flair == "Opinion Piece"
    assert post.is_nsfw is False
    assert post.is_spoiler is False
    assert post.num_comments == 978


def test_parses_post_permalink(example_post_html: str) -> None:
    post = parse_reddit_post_html(example_post_html)

    expected_permalink = (
        "/r/Games/comments/1lqa2hj/has_xbox_considered_laying_one_person_off_instead/"
    )
    assert post.permalink == expected_permalink


def test_parses_post_date(example_post_html: str) -> None:
    post = parse_reddit_post_html(example_post_html)

    assert post.date_posted is not None
    assert post.date_posted.year == 2025
    assert post.date_posted.month == 7
    assert post.date_posted.day == 2


def test_parses_comments(example_post_html: str) -> None:
    post = parse_reddit_post_html(example_post_html)

    assert len(post.comments) > 0
    first_comment = post.comments[0]

    assert first_comment.comment_id == "n113cp2"
    assert first_comment.post_id == "1lqa2hj"
    assert first_comment.score == 2215
    assert first_comment.depth == 0


def test_parses_nested_comments(example_post_html: str) -> None:
    post = parse_reddit_post_html(example_post_html)

    first_comment = post.comments[0]
    assert len(first_comment.children) > 0

    first_child = first_comment.children[0]
    assert first_child.comment_id == "n113i94"
    assert first_child.author == "ComprehensiveArt7725"
    assert first_child.depth == 1


def test_parses_deleted_comment(example_post_html: str) -> None:
    post = parse_reddit_post_html(example_post_html)

    first_comment = post.comments[0]
    assert first_comment.author == "[deleted]"


def test_raises_for_invalid_html() -> None:
    with pytest.raises(RedditScraperError):
        parse_reddit_post_html("<html><body>No post here</body></html>")
