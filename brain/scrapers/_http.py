import random
import time

import requests

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
_last = {}


def get(url: str, *, as_json: bool = False, timeout: int = 25, min_gap: float = 1.5, headers: dict | None = None):
    """Polite GET: identifies as a normal browser, waits `min_gap` seconds between hits to the same host."""
    host = url.split("/")[2]
    wait = min_gap - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait + random.uniform(0, 0.4))
    _last[host] = time.time()
    r = requests.get(url, timeout=timeout, headers={"User-Agent": UA, "Accept-Language": "en", **(headers or {})})
    r.raise_for_status()
    return r.json() if as_json else r.text
