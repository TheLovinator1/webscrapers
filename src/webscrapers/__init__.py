from urllib.parse import urljoin

from rnet import Client
from rnet import Impersonate
from rnet import Response


async def download_page(url: str) -> str:
    """Download the content of a web page given its URL.

    Args:
        url (str): The URL of the web page to download.

    Raises:
        RuntimeError: If no response is received after following redirects.

    Returns:
        str: The content of the web page.
    """
    client = Client(impersonate=Impersonate.Chrome137)
    max_redirects = 5
    resp: Response | None = None
    for _ in range(max_redirects):
        resp = await client.get(url)
        # If status is 301/302, follow the Location header
        if resp.status in {301, 302, 303, 307, 308}:
            location: bytes | None = resp.headers.get("Location")
            if not location:
                break

            # rnet may return bytes for headers, decode if needed
            # Always convert location to str
            if isinstance(location, bytes):
                location_str: str = location.decode("utf-8")
            else:
                location_str = str(location)

            # Handle relative redirects
            if location_str.startswith("/"):
                url = urljoin(url, location_str)
            else:
                url = location_str
            continue
        return await resp.text()

    # If too many redirects or no valid response, return last response text
    if resp is not None:
        return await resp.text()

    msg = "No response received from client.get()"
    raise RuntimeError(msg)
