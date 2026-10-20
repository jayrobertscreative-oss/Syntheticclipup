"""YouTube link inspection via the official YouTube Data API v3.

The Data API returns metadata only. It does not provide the video file, and
caption downloads require OAuth authorisation for a channel you manage. So this
module never claims a YouTube link can be clipped directly; it tells the user
to upload their original file.
"""
import re
from urllib.parse import parse_qs, urlparse

import requests

from . import config

_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_id(url: str) -> str | None:
    url = url.strip()
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    u = urlparse(url)
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.").removeprefix("music.")
    vid = None
    if host == "youtu.be":
        vid = u.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "youtube-nocookie.com"):
        parts = [p for p in u.path.split("/") if p]
        if u.path == "/watch" or (parts and parts[0] == "watch"):
            vid = (parse_qs(u.query).get("v") or [None])[0]
        elif parts and parts[0] in ("shorts", "embed", "live", "v") and len(parts) > 1:
            vid = parts[1]
    return vid if vid and _ID.match(vid) else None


def _iso_duration(s: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return 0
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


MEDIA_NOTE = ("YouTube's official API provides details about a video but not the video file itself. "
              "To clip it, upload your original file. If it's on your channel, you can download it from YouTube Studio.")


def inspect(url: str) -> dict:
    vid = extract_id(url)
    if not vid:
        return {"ok": False, "error": "That isn't a YouTube video link. Use a youtube.com/watch, youtu.be or /shorts/ link."}
    result = {"ok": True, "video_id": vid, "can_process_from_link": False, "media_note": MEDIA_NOTE}
    if not config.YOUTUBE_API_KEY:
        result.update(metadata=None, accessible=None,
                      access_note="Video details are unavailable because YOUTUBE_API_KEY isn't set on the server.")
        return result
    r = requests.get("https://www.googleapis.com/youtube/v3/videos",
                     params={"id": vid, "part": "snippet,contentDetails,status", "key": config.YOUTUBE_API_KEY},
                     timeout=15)
    if r.status_code != 200:
        msg = (r.json().get("error") or {}).get("message", r.text[:200]) if r.headers.get("content-type", "").startswith("application/json") else r.text[:200]
        return {"ok": False, "error": f"YouTube API error ({r.status_code}): {msg}"}
    items = r.json().get("items", [])
    if not items:
        result.update(metadata=None, accessible=False,
                      access_note="YouTube didn't return this video. It may be private, deleted or the ID is wrong.")
        return result
    it = items[0]
    sn, cd, st = it.get("snippet", {}), it.get("contentDetails", {}), it.get("status", {})
    thumbs = sn.get("thumbnails", {})
    thumb = (thumbs.get("maxres") or thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url")
    privacy = st.get("privacyStatus")
    accessible = privacy in ("public", "unlisted") and st.get("uploadStatus") == "processed"
    result.update(
        accessible=accessible,
        metadata={"title": sn.get("title"), "channel": sn.get("channelTitle"), "thumbnail": thumb,
                  "duration_s": _iso_duration(cd.get("duration", "")), "privacy": privacy,
                  "license": st.get("license"), "embeddable": st.get("embeddable"),
                  "region_restricted": bool(cd.get("regionRestriction"))},
        access_note=("The video is publicly viewable. Viewable is not the same as permission to download or edit it."
                     if accessible else f"The video isn't publicly available (status: {privacy})."),
    )
    return result
