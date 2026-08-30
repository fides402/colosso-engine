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
import sys
import time

import paths_boot  # noqa: F401
import discogs_ext


def collect_candidates(profile: str, target: int) -> list[dict]:
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

    seen_release_ids: set = set()
    seen_keys: set = set()
    results: list[dict] = []

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
        for c in cands:
            key = (c["artist"].strip().lower(), c["title"].strip().lower())
            if key in seen_keys:
                continue
            seen_keys.add(key)
            results.append(c)
            added += 1
        print(f"round {rnd}: +{added} new (total {len(results)}/{want}), "
              f"{diag.get('releases_found', 0)} releases scanned", flush=True)
        if added == 0 and rnd > 3:
            break

    return results[:want]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True, choices=list(discogs_ext.GENRE_MAP.keys()))
    ap.add_argument("--target", type=int, default=25)
    ap.add_argument("--out", default="out.json")
    args = ap.parse_args()

    t0 = time.time()
    results = collect_candidates(args.profile, args.target)
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
