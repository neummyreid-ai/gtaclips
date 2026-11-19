#!/usr/bin/env python3
"""Clip finder: lists each streamer's top Twitch clips from the last 24h,
plus the most-replayed moments of YouTube-only streamers' newest videos.

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
# Streamers whose GTA 6 content is on YouTube instead of Twitch clips.
# For these, the finder takes their newest videos/streams and turns the
# "most replayed" peaks into clip candidates (with a start time).
YOUTUBE_CHANNELS = {
    "tomo": "https://www.youtube.com/@Tomovids",
}
YT_VIDEOS_PER_CHANNEL = 4
YT_PEAKS_PER_VIDEO = 3
YT_CLIP_LEN = 30
ERRORS = []  # saved into latest.json so problems are visible without the Actions log
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


def ytdlp_json(args, timeout=240):
    try:
        res = subprocess.run(["yt-dlp", *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    if res.returncode != 0 or not res.stdout.strip():
        print(f"yt-dlp failed {args[-1]}: {res.stderr[-300:]}", file=sys.stderr)
        ERRORS.append({"url": args[-1], "error": res.stderr.strip()[-300:]})
        return None
    return json.loads(res.stdout)


def heat_peaks(heatmap, duration, n, length):
    """Pick the n most-replayed, non-overlapping windows of `length` seconds."""
    picks = []
    for seg in sorted(heatmap or [], key=lambda s: s.get("value", 0), reverse=True):
        mid = (seg["start_time"] + seg["end_time"]) / 2
        start = max(0, min(mid - length / 2, (duration or mid + length) - length))
        if all(abs(start - p[0]) >= length for p in picks):
            picks.append((round(start), seg.get("value", 0)))
        if len(picks) >= n:
            break
    return picks


def list_youtube(name, channel_url):
    vids = []
    for tab in ("streams", "videos"):
        data = ytdlp_json(["--flat-playlist", "-J", "--playlist-end",
                           str(YT_VIDEOS_PER_CHANNEL), f"{channel_url}/{tab}"])
        for e in (data or {}).get("entries") or []:
            if e.get("id") and e["id"] not in {v["id"] for v in vids}:
                vids.append(e)
    clips = []
    for v in vids[:YT_VIDEOS_PER_CHANNEL]:
        url = f"https://www.youtube.com/watch?v={v['id']}"
        info = ytdlp_json(["-J", "--skip-download", "--no-playlist", url])
        if not info or info.get("is_live"):
            continue
        dur = info.get("duration") or 0
        for start, heat in heat_peaks(info.get("heatmap"), dur, YT_PEAKS_PER_VIDEO, YT_CLIP_LEN):
            clips.append({
                "id": f"yt-{v['id']}-{start}",
                "streamer": name,
                "title": f"{info.get('title')} @ {start // 3600}:{start // 60 % 60:02d}:{start % 60:02d}",
                "views": info.get("view_count") or 0,
                "duration": YT_CLIP_LEN,
                "url": url,
                "start": start,
                "heat": round(heat, 3),
                "created": info.get("timestamp"),
                "thumbnail": info.get("thumbnail"),
                "game": None,
                "source": "youtube",
            })
    print(f"[{name} youtube] {len(vids)} videos, {len(clips)} peaks")
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
    yt = []
    for name, url in YOUTUBE_CHANNELS.items():
        yt.extend(list_youtube(name, url))
    clips.extend(yt)  # listed after the Twitch clips; views are whole-video views
    for c in clips:
        g = (c.get("game") or "").lower()
        c["is_gta6"] = ("grand theft auto vi" in g) or ("gta 6" in g) or ("gta vi" in g)
    save_thumbs(clips)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "count": len(clips),
            "errors": ERRORS,
            "clips": clips,
        }, f, indent=1)
    print(f"saved {len(clips)} clips")


if __name__ == "__main__":
    main()
