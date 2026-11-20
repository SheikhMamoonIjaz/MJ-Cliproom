"""Recent public YouTube search references for clip metadata."""
import html
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

import httpx

from . import accounts, brain, config, ctx

_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_CACHE_SECONDS = 900
_cache = OrderedDict()
_lock = threading.Lock()


def _cached_search(query, region, account, api_key):
    # Keep repeat requests for the same topic off the quota bucket. The cache is
    # short lived, held in memory only, and never exposes a credential.
    account_id = account["id"] if account else "research-key"
    key = (ctx.uid(), account_id, region, query.casefold())
    now = time.monotonic()
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] > now:
            _cache.move_to_end(key)
            return cached[1]

    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds").replace("+00:00", "Z")
    params = {"part": "snippet", "type": "video", "maxResults": 8, "videoCategoryId": "20",
              "videoDuration": "short", "publishedAfter": since, "order": "viewCount", "regionCode": region,
              "q": query, "fields": "items(id/videoId,snippet(title,publishedAt))"}
    headers = {}
    if api_key:
        params["key"] = api_key
    else:
        headers["Authorization"] = f"Bearer {accounts._yt_token(account)}"
    response = httpx.get(_SEARCH_URL, params=params, headers=headers, timeout=12)
    accounts._check(response, "Reading YouTube topic search")
    sources = []
    for item in response.json().get("items", []):
        snippet = item.get("snippet", {})
        video_id = item.get("id", {}).get("videoId", "")
        title = brain._safe(html.unescape(str(snippet.get("title") or "")), 180)
        if title and _VIDEO_ID.fullmatch(video_id):
            sources.append({"title": title, "url": f"https://www.youtube.com/watch?v={video_id}",
                            "published_at": str(snippet.get("publishedAt") or "")[:10]})
    with _lock:
        _cache[key] = (time.monotonic() + _CACHE_SECONDS, sources)
        _cache.move_to_end(key)
        while len(_cache) > 64:
            _cache.popitem(last=False)
    return sources


def for_clip(title, uploader, transcript, region="US", *, infer_topic=True):
    """Find a topic with the LLM, then read recent public search results from YouTube."""
    region = region.upper() if isinstance(region, str) else ""
    if not re.fullmatch(r"[A-Z]{2}", region):
        region = "US"
    result = {"status": "unavailable", "region": region, "query": "", "sources": [], "message": ""}
    api_key = str(config.env("PEAKCUT_YOUTUBE_RESEARCH_KEY", "") or "").strip()
    account = None
    if not api_key:
        user_accounts = sorted(a["id"] for a in accounts.list_accounts() if a["platform"] == "youtube")
        if user_accounts:
            account = accounts.get(user_accounts[0])
        if not account:
            return {**result, "message": "Connect YouTube in Settings to include recent YouTube search results."}

    if infer_topic:
        query = brain.clip_research_query(title, uploader, transcript)
    else:
        game = brain._game_label(title)
        query = game + " gameplay" if game != "gaming" else ""
    result["query"] = query
    if not query:
        return {**result, "message": "The clip has too little topic context for a useful YouTube search."}
    try:
        sources = _cached_search(query, region, account, api_key)
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError, TypeError):
        return {**result, "message": "YouTube search could not respond. Check the connection or search quota and retry."}
    if not sources:
        return {**result, "message": "YouTube returned no recent gaming results for this topic in the selected region."}
    return {**result, "status": "researched", "sources": sources,
            "message": "Recent YouTube results ordered by view count. These are topic references."}
