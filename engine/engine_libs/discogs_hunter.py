"""Discogs API integration for SampleHunter.

Finds random releases matching user-specified filters (genre, style, label,
year range, country), extracts their tracklists, and returns search targets
for YouTube lookup.
"""
import os as _os
import random
import re
import time

import requests
import lastfm

DISCOGS_TOKEN = _os.environ.get("DISCOGS_TOKEN", "fvYYQHvhAEHVshXGPHYtbAWSlTUNQpnNJcBBbYCB")
BASE = "https://api.discogs.com"
HEADERS = {
    "Authorization": f"Discogs token={DISCOGS_TOKEN}",
    "User-Agent": "DIGMORE/1.0",
}

_DISAMBIG = re.compile(r"\s*\(\d+\)\s*$")


def _clean(name: str) -> str:
    return _DISAMBIG.sub("", name).strip()


def _get(path: str, params: dict = None, retries: int = 2) -> dict:
    for attempt in range(retries + 1):
        try:
            r = requests.get(f"{BASE}{path}", params=params,
                             headers=HEADERS, timeout=12)
            if r.status_code == 429:
                time.sleep(60)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == retries:
                raise
            time.sleep(1)
    return {}


def search_releases(
    genre: str = "",
    style: str = "",
    label: str = "",
    year_from: int = None,
    year_to: int = None,
    country: str = "",
    max_have: int = 500,
    n: int = 20,
    exclude_ids: set = None,
) -> list[dict]:
    """Return up to `n` randomly-sampled releases matching the filters.

    max_have: skip releases where community.have > this value (popularity cap).
    exclude_ids: release IDs already processed — skip them to guarantee variety.
    Each call randomizes which Discogs pages are fetched so repeat calls with
    the same filters return different records.
    """
    params = {"per_page": 50, "type": "release", "page": 1}
    if genre:   params["genre"]   = genre
    if style:   params["style"]   = style
    if label:   params["label"]   = label
    if country: params["country"] = country

    # Probe page 1 just to learn total_pages, then pick random pages.
    data = _get("/database/search", params)
    total_pages = min(data.get("pagination", {}).get("pages", 1), 30)

    # Randomize which pages we fetch: shuffle all available, take first 4.
    all_pages = list(range(1, total_pages + 1))
    random.shuffle(all_pages)
    pages_to_fetch = all_pages[:min(4, total_pages)]

    results = []
    for pg in pages_to_fetch:
        params["page"] = pg
        try:
            results.extend(_get("/database/search", params).get("results", []))
            time.sleep(0.4)
        except Exception:
            continue

    # Popularity filter
    if max_have and max_have > 0:
        results = [r for r in results
                   if int((r.get("community") or {}).get("have", 0)) <= max_have]

    # Year range filter
    if year_from or year_to:
        yf = year_from or 0
        yt_ = year_to or 9999
        results = [r for r in results
                   if yf <= int(r.get("year") or 0) <= yt_]

    # Exclude already-processed releases to guarantee fresh variety
    if exclude_ids:
        results = [r for r in results if r.get("id") not in exclude_ids]

    random.shuffle(results)
    return results[:n]


def get_tracklist(release_id: int) -> list[dict]:
    """Return [{artist, title}] for a release."""
    data = _get(f"/releases/{release_id}")
    album_artists = [_clean(a["name"]) for a in data.get("artists", [])]
    album_artist = " & ".join(album_artists) if album_artists else ""

    tracks = []
    for t in data.get("tracklist", []):
        title = (t.get("title") or "").strip()
        if not title:
            continue
        ta = t.get("artists", [])
        artist = _clean(ta[0]["name"]) if ta else album_artist
        tracks.append({"artist": artist, "title": title})
    return tracks


def build_candidates(
    genre: str = "",
    style: str = "",
    label: str = "",
    year_from: int = None,
    year_to: int = None,
    country: str = "",
    max_have: int = 500,
    max_listeners: int = 500_000,
    n_releases: int = 15,
    tracks_per_release: int = 3,
    exclude_ids: set = None,
) -> tuple[list[dict], dict]:
    """Return (candidates, diag) where diag contains pipeline attrition counts.

    max_listeners: skip tracks whose artist has more Last.fm listeners than this.
    exclude_ids: release IDs to skip (for loop-mode variety across rounds).
    """
    releases = search_releases(genre, style, label, year_from, year_to,
                               country, max_have=max_have, n=n_releases,
                               exclude_ids=exclude_ids)
    diag = {"releases_found": len(releases), "tracks_total": 0, "filtered_famous": 0}
    candidates = []
    for rel in releases:
        try:
            tracks = get_tracklist(rel["id"])
            if not tracks:
                continue
            chosen = random.sample(tracks, min(tracks_per_release, len(tracks)))
            diag["tracks_total"] += len(chosen)
            for t in chosen:
                if lastfm.is_too_famous(t["artist"], max_listeners):
                    diag["filtered_famous"] += 1
                    continue
                candidates.append({
                    "artist":        t["artist"],
                    "title":         t["title"],
                    "release_title": rel.get("title", ""),
                    "year":          rel.get("year"),
                    "label":         (rel.get("label") or [""])[0],
                    "country":       rel.get("country", ""),
                    "discogs_id":    rel["id"],
                    "genres":        rel.get("genre", []),
                    "styles":        rel.get("style", []),
                })
            time.sleep(0.4)   # ~60 req/min limit
        except Exception:
            continue

    random.shuffle(candidates)
    return candidates, diag
