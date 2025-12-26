from __future__ import annotations

import asyncio
import logging
import pprint
import sys
from pathlib import Path

from loguru import logger

from webscrapers.reddit import RedditPostData
from webscrapers.reddit import scrape_post


def main() -> None:
    """Scrape a Reddit post from command line argument and pretty print the result."""
    # Configure logging to show DEBUG messages
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    if len(sys.argv) < 2:  # noqa: PLR2004
        sys.exit(1)
    url: str = sys.argv[1]

    async def run() -> None:
        post_data: RedditPostData = await scrape_post(post_url=url)
        logger.debug(pprint.pformat(post_data))
        logger.info("Scraped Reddit post from URL: {}", url)

        # Save to JSON file
        output_path = Path("reddit_post.json")
        output_path.write_text(  # noqa: ASYNC240
            RedditPostData.model_validate(post_data).model_dump_json(indent=4),
            encoding="utf-8",
        )
        logger.info("Saved scraped data to {}", output_path)

    asyncio.run(run())


if __name__ == "__main__":
    main()
