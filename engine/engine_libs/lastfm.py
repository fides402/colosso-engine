"""Last.fm API — artist popularity check.

Uses artist.getinfo to fetch listener count, which is the best proxy for
how famous an artist is. Results are cached in-process to avoid repeat calls.
"""
import requests

API_KEY = "20d53ce8960991e92519bfdb212a51bd"
BASE = "http://ws.audioscrobbler.com/2.0/"

_cache: dict[str, int | None] = {}   # lowercased name → listener count or None


def get_listeners(artist: str) -> int | None:
    """Return Last.fm listener count, or None if artist not found / API error."""
    key = artist.strip().lower()
    if key in _cache:
        return _cache[key]
    try:
        r = requests.get(BASE, params={
            "method": "artist.getinfo",
            "artist": artist,
            "api_key": API_KEY,
            "format": "json",
            "autocorrect": 1,
        }, timeout=8)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            _cache[key] = None
            return None
        count = int(data["artist"]["stats"]["listeners"])
        _cache[key] = count
        return count
    except Exception:
        _cache[key] = None
        return None


def get_similar_tracks(artist: str, title: str, limit: int = 15) -> list[dict]:
    """Return similar tracks from Last.fm. Each: {artist, title, match} (match 0-1)."""
    try:
        r = requests.get(BASE, params={
            "method":      "track.getSimilar",
            "artist":      artist,
            "track":       title,
            "api_key":     API_KEY,
            "format":      "json",
            "limit":       limit,
            "autocorrect": 1,
        }, timeout=8)
        r.raise_for_status()
        data = r.json()
        tracks = data.get("similartracks", {}).get("track", [])
        return [
            {
                "artist": t["artist"]["name"],
                "title":  t["name"],
                "match":  float(t.get("match", 0)),
            }
            for t in tracks
        ]
    except Exception:
        return []


def is_too_famous(artist: str, max_listeners: int) -> bool:
    """True if artist exceeds the listener cap.

    If the artist isn't on Last.fm (count=None) we assume they're obscure and
    return False so the track stays in the candidate pool.
    """
    if max_listeners <= 0:
        return False
    count = get_listeners(artist)
    if count is None:
        return False   # unknown → keep
    return count > max_listeners
