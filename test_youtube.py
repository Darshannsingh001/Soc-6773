import json
import os
import urllib.error
import urllib.parse
import urllib.request

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")

if not YOUTUBE_API_KEY:
    print("ERROR: YOUTUBE_API_KEY secret is not set or empty.")
    exit(1)

query = "CISF"
params = {
    "part": "snippet",
    "q": query,
    "type": "video",
    "order": "date",
    "maxResults": 5,
    "key": YOUTUBE_API_KEY.strip(),  # Strip accidental whitespace
}

url = f"https://www.googleapis.com/youtube/v3/search?{urllib.parse.urlencode(params)}"

try:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    items = data.get("items", [])
    print(f"SUCCESS! Found {len(items)} videos for query '{query}':\n")
    for item in items:
        title = item["snippet"]["title"]
        video_id = item["id"]["videoId"]
        print(f"- {title}\n  https://www.youtube.com/watch?v={video_id}")

except urllib.error.HTTPError as e:
    error_body = e.read().decode("utf-8")
    print(f"FAILED with HTTP Error {e.code}:\n{error_body}")
except Exception as e:
    print(f"FAILED: {e}")
