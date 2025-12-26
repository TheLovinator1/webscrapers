import pytest

from webscrapers.reddit import RedditScraperError
from webscrapers.reddit import RedditUrlInfo
from webscrapers.reddit import get_reddit_id_from_url


def test_parses_standard_post_url() -> None:
    url = (
        "https://old.reddit.com/r/homelab/comments/"
        "g76orz/i_bought_a_nintendo_switch_but_it_looks_a_little/"
    )
    info: RedditUrlInfo = get_reddit_id_from_url(url)

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
