"""Non-interactive entrypoint for a GitHub Actions runner: generate one
DIGMORE playlist for a profile and dump the results as JSON.

DISCOGS ONLY — no YouTube, no CLAP here. Both were tried in the cloud and
both are impossible from a GitHub Actions IP: YouTube refuses
watch/player-response requests from that IP class outright
(SignInConfirmNotBotException), and it keeps refusing with a fully
authenticated cookie export from a real logged-in session — verified live
on 28/08/2026, first with NewPipeExtractor (newpipe-cli/, still in the repo,
unused) and then with yt-dlp, whose cookie auth is the mature reference
implementation. Two independent clients, same wall: it's a check on where
the session is being used from, not on whether the cookies are valid.

Real CLAP scoring still happens — on the PHONE, which has an ordinary
mobile/home IP that YouTube serves normally. diggaplayer resolves each
candidate, pulls a snippet, and POSTs it to the engine's /api/embed (see
app.py) for the actual CLAP similarity. So this script's job is only to
produce good Discogs candidates, fast.

Usage:
    python generate_cli.py --profile jazz --target 30 --out out.json
"""
import argparse
import json
import os
import sys
import time

import paths_boot  # noqa: F401
import discogs_ext

# Cap on how many historical keys/ids we carry forward run to run. Growth is
# slow (at most ~60 accepted tracks per run, a handful of runs/day), so this
# covers many months of usage before anything gets evicted; it exists only so
# the file can never grow unbounded over years of use.
MAX_HISTORY = 20_000


def load_seen(path: str) -> tuple[set, set]:
    """Cross-run memory of what this profile has already delivered.

    Without this, every GitHub Actions dispatch starts `seen_release_ids`
    empty (see collect_candidates) and random.shuffle over a fairly small
    catalogue (year window 1969-1983 + rating gate) keeps re-surfacing the
    same releases run after run — measured 2026-09-06: 128 of the last 150
    candidates delivered to the phone had already been judged there. Persists
    both release ids (skips re-fetching a tracklist already mined) and track
    keys (catches the same track resurfacing via a different release, e.g. a
    compilation or reissue).
    """
    if not os.path.exists(path):
        return set(), set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        release_ids = set(data.get("release_ids", []))
        track_keys = {tuple(k) for k in data.get("track_keys", [])}
        return release_ids, track_keys
    except Exception:
        return set(), set()


def save_seen(path: str, release_ids: set, track_keys: set) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "release_ids": list(release_ids)[-MAX_HISTORY:],
            "track_keys": [list(k) for k in list(track_keys)[-MAX_HISTORY:]],
        }, f)


def collect_candidates(profile: str, target: int, seen_path: str) -> list[dict]:
    """Discogs candidates for `profile`, deduplicated by (artist, title).

    Overshoots the target on purpose: many obscure vinyl-only credits aren't
    on Spotify at all, and that filtering happens later on the phone.
    """
    # 2x, not 4x. Roughly two thirds of Discogs candidates turn out to exist
    # on Spotify (measured: 66 of 100), so 2x still comfortably clears the
    # target — and every extra candidate costs a Discogs round here AND a
    # Spotify search + YouTube resolve + CLAP score on the phone later, which
    # is what actually made a run feel slow.
    OVERSHOOT = 2
    MAX_ROUNDS = 12
    want = max(target * OVERSHOOT, 30)

    # Reported live 2026-09-06: "the same artists or tracks from the same album keep coming
    # back". seen_keys (above) only ever stops the EXACT same track from resurfacing — it
    # says nothing about a single delivered batch having 4 tracks off one record, or the
    # same prolific artist winning the random release sample repeatedly. Capped per-run,
    # not persisted: this is about one delivered batch not being monotonous, not about
    # taste (measured in HANDOFF_FEEDBACK_LOOP.md: artist alone predicts nothing, AUC at
    # chance — so this is a presentation constraint, not a taste rule).
    MAX_PER_ARTIST = 3
    MAX_PER_RELEASE = 2

    seen_release_ids, seen_keys = load_seen(seen_path)
    history_release_count = len(seen_release_ids)
    history_key_count = len(seen_keys)
    results: list[dict] = []
    artist_counts: dict = {}
    release_counts: dict = {}

    for rnd in range(1, MAX_ROUNDS + 1):
        if len(results) >= want:
            break
        cands, diag = discogs_ext.build_candidates(
            profile,
            exclude_ids=seen_release_ids,
            n_releases=18,
            tracks_per_release=4,
        )
        seen_release_ids.update(diag.get("release_ids", []))
        added = 0
        capped = 0
        for c in cands:
            key = (c["artist"].strip().lower(), c["title"].strip().lower())
            if key in seen_keys:
                continue
            artist_key = c["artist"].strip().lower()
            release_key = (c.get("release_title") or "").strip().lower()
            if artist_counts.get(artist_key, 0) >= MAX_PER_ARTIST or \
                    (release_key and release_counts.get(release_key, 0) >= MAX_PER_RELEASE):
                capped += 1
                continue
            seen_keys.add(key)
            results.append(c)
            artist_counts[artist_key] = artist_counts.get(artist_key, 0) + 1
            if release_key:
                release_counts[release_key] = release_counts.get(release_key, 0) + 1
            added += 1
        print(f"round {rnd}: +{added} new (total {len(results)}/{want}), "
              f"{capped} skipped for artist/album variety, "
              f"{diag.get('releases_found', 0)} releases scanned "
              f"[history: {history_release_count} releases, {history_key_count} tracks]", flush=True)
        if added == 0 and rnd > 3:
            break

    # Persist regardless of whether `want` was reached: even a partial run's
    # exploration should count against future runs, and this is what
    # actually stops the re-pescaggio across separate Action dispatches.
    save_seen(seen_path, seen_release_ids, seen_keys)

    return results[:want]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True, choices=list(discogs_ext.GENRE_MAP.keys()))
    ap.add_argument("--target", type=int, default=25)
    ap.add_argument("--out", default="out.json")
    ap.add_argument("--seen", default=None,
                     help="Path to this profile's cross-run seen-releases/seen-tracks file "
                          "(persists what was already delivered, so re-dispatching the "
                          "workflow doesn't just re-shuffle the same catalogue).")
    args = ap.parse_args()

    seen_path = args.seen or f"seen-{args.profile}.json"

    t0 = time.time()
    results = collect_candidates(args.profile, args.target, seen_path)
    print(f"status=done found={len(results)} elapsed={time.time() - t0:.1f}s", flush=True)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({
            "profile": args.profile,
            "status": "done",
            "results": results,
        }, f, ensure_ascii=False, indent=2)

    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
