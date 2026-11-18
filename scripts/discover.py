#!/usr/bin/env python3
"""Clip finder: lists each streamer's top Twitch clips from the last 24h.

Writes discover/latest.json (all clips, sorted by views) and saves a
thumbnail for the top clips in discover/thumbs/ so frames can be checked
before posting.
"""
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

STREAMERS = [
    "kaicenat", "ishowspeed", "typicalgamer", "jynxzi", "adinross",
    "darkviperau", "xqc", "lacy", "clix", "n3on", "caseoh_", "tomo",
    "dasgasd3m",
]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "discover", "latest.json")
THUMBS = os.path.join(ROOT, "discover", "thumbs")
TOP_THUMBS = 40
# Public web client id that Twitch's own site (and yt-dlp) uses for GQL.
GQL_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"


def list_clips(channel):
    url = f"https://www.twitch.tv/{channel}/clips?filter=clips&range=24hr"
    try:
        res = subprocess.run(
            ["yt-dlp", "--flat-playlist", "-J", "--playlist-end", "60", url],
            capture_output=True, text=True, timeout=180,
        )
    except subprocess.TimeoutExpired:
        print(f"[{channel}] timed out", file=sys.stderr)
        return []
    if res.returncode != 0 or not res.stdout.strip():
        print(f"[{channel}] yt-dlp failed: {res.stderr[-400:]}", file=sys.stderr)
        return []
    data = json.loads(res.stdout)
    clips = []
    for e in data.get("entries") or []:
        thumbs = e.get("thumbnails") or []
        clips.append({
            "id": e.get("id"),
            "streamer": channel,
            "title": e.get("title"),
            "views": e.get("view_count") or 0,
            "duration": e.get("duration"),
            "url": e.get("url") or e.get("webpage_url"),
            "created": e.get("timestamp"),
            "thumbnail": thumbs[-1]["url"] if thumbs else None,
            "game": None,
        })
    print(f"[{channel}] {len(clips)} clips")
    return clips


def slug_from_url(url):
    if not url:
        return None
    url = url.rstrip("/").split("?")[0]
    return url.split("/")[-1]


def add_games(clips):
    """Best effort: ask Twitch GQL which game each clip is from."""
    slugs = [slug_from_url(c["url"]) for c in clips]
    for i in range(0, len(clips), 25):
        batch = [(j, s) for j, s in enumerate(slugs[i:i + 25], start=i) if s]
        if not batch:
            continue
        query = "{ " + " ".join(
            f'c{j}: clip(slug: {json.dumps(s)}) {{ game {{ name }} }}' for j, s in batch
        ) + " }"
        req = urllib.request.Request(
            "https://gql.twitch.tv/gql",
            data=json.dumps({"query": query}).encode(),
            headers={"Client-ID": GQL_CLIENT_ID, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.load(r).get("data") or {}
        except Exception as exc:  # GQL is optional
            print(f"game lookup failed: {exc}", file=sys.stderr)
            return
        for j, _ in batch:
            node = data.get(f"c{j}") or {}
            game = node.get("game") or {}
            clips[j]["game"] = game.get("name")


def save_thumbs(clips):
    os.makedirs(THUMBS, exist_ok=True)
    keep = set()
    for c in clips[:TOP_THUMBS]:
        if not c.get("thumbnail") or not c.get("id"):
            continue
        path = os.path.join(THUMBS, f"{c['id']}.jpg")
        keep.add(os.path.basename(path))
        if os.path.exists(path):
            continue
        try:
            urllib.request.urlretrieve(c["thumbnail"], path)
        except Exception as exc:
            print(f"thumb failed {c['id']}: {exc}", file=sys.stderr)
    for name in os.listdir(THUMBS):  # keep the folder small
        if name not in keep:
            os.remove(os.path.join(THUMBS, name))


def main():
    clips = []
    for s in STREAMERS:
        clips.extend(list_clips(s))
    clips = [c for c in clips if c.get("url")]
    clips.sort(key=lambda c: c["views"], reverse=True)
    add_games(clips)
    for c in clips:
        g = (c.get("game") or "").lower()
        c["is_gta6"] = ("grand theft auto vi" in g) or ("gta 6" in g) or ("gta vi" in g)
    save_thumbs(clips)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "count": len(clips),
            "clips": clips,
        }, f, indent=1)
    print(f"saved {len(clips)} clips")


if __name__ == "__main__":
    main()
