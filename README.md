# gtaclips

Automatic clip pipeline for **Vice City Clipped**, a GTA 6 clip page. Fan page, not affiliated with Rockstar Games.

- `discover.yml` runs every 30 minutes (and on pushes) and lists each streamer's top Twitch clips from the last 24 hours in `discover/latest.json`, sorted by views, plus thumbnails of the top clips in `discover/thumbs/`.
- `clip.yml` runs when a `jobs/*.json` file is pushed. It downloads the clip and renders a 1080x1920 Vice City-style vertical video into `out/<id>.mp4`.
- Finished videos are posted through Metricool from `https://raw.githubusercontent.com/<user>/gtaclips/main/out/<id>.mp4`.

## Job file

```json
{
  "id": "kai-first-chase",
  "url": "https://www.twitch.tv/kaicenat/clip/...",
  "caption": "Kai waited 13 years for this",
  "emoji": "😮",
  "credit": "Clip: Kai Cenat on Twitch",
  "dur": 30
}
```

`dur` is how many seconds to keep from the start (`null` keeps the whole clip).

## Credits

Every clip credits its streamer. If you're a creator and want a clip removed, open an issue and it will be taken down the same day.

Fonts: Anton and Noto Color Emoji, both under the SIL Open Font License.
