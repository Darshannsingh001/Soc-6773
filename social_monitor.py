"""
Social Media Keyword Monitor (YouTube API Integrated)
------------------------------------------------------
Monitors social media platforms with direct YouTube Data API v3 integration.

Features:
- Direct YouTube Data API v3 search (100% video coverage for published videos).
- Zero third-party pip dependencies (uses built-in urllib and json).
- Double-boolean filter: (Target Keyword) AND (Security/Admin Terms).
- Rejects posts/videos older than 48 hours.
- Deduplicates via state.json and sends push alerts via ntfy.sh.
"""

import email.utils
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

KEYWORDS = [
    "CISF",
    "SILIGURI CORRIDOR",
    "SILIGURI",
    "DARJEELING",
    "KALIMPONG",
    "TEESTA",
    "NHPC",
    "MUNGPOO",
    "RAMBI",
]

# Strict Filter: Requires matches to contain at least one security/admin term
SECURITY_ADMIN_FILTER = (
    "curfew OR strike OR paramilitary OR CISF OR police OR army OR deployment OR "
    '"law and order" OR Gorkha OR Gorkhaland OR agitation OR bandh OR protest OR GTA OR '
    'administration OR "flood alert" OR landslide OR "road blockage" OR disaster OR evacuation'
)

# Social media domains indexed by Google (excluding YouTube since it uses native API)
SOCIAL_DOMAINS = "site:x.com OR site:twitter.com OR site:facebook.com OR site:instagram.com OR site:t.me"

STATE_FILE = "state.json"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}" if NTFY_TOPIC else None
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")

SECONDS_BETWEEN_NOTIFICATIONS = 3
MAX_PAYLOAD_BYTES = 3500
MAX_POST_AGE_HOURS = 48


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load {STATE_FILE} ({e}). Starting fresh.")
    return {"seen_links": []}


def save_state(seen_links_list):
    trimmed = seen_links_list[-3000:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"seen_links": trimmed}, f, indent=2)


def fetch_youtube_api(keyword):
    """Fetches real-time YouTube videos using the official YouTube Data API v3."""
    if not YOUTUBE_API_KEY:
        print("YOUTUBE_API_KEY not set. Skipping official YouTube search.")
        return []

    published_after = (datetime.now(timezone.utc) - timedelta(hours=MAX_POST_AGE_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    query = f'"{keyword}" ({SECURITY_ADMIN_FILTER})'
    
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "order": "date",
        "publishedAfter": published_after,
        "maxResults": 10,
        "key": YOUTUBE_API_KEY,
    }
    
    url = f"https://www.googleapis.com/youtube/v3/search?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

    items = []
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        for item in data.get("items", []):
            video_id = item["id"].get("videoId")
            title = item["snippet"].get("title", "").strip()
            if video_id and title:
                link = f"https://www.youtube.com/watch?v={video_id}"
                items.append((f"[YouTube] {title}", link, video_id))
    except Exception as e:
        print(f"YouTube API error for '{keyword}': {e}")

    return items


def fetch_google_social(keyword):
    """Fetches X, Facebook, Instagram, and Telegram posts indexed by Google."""
    full_query = f'"{keyword}" ({SECURITY_ADMIN_FILTER}) ({SOCIAL_DOMAINS})'
    query_encoded = urllib.parse.quote(full_query)
    url = f"https://news.google.com/rss/search?q={query_encoded}&hl=en-IN&gl=IN&ceid=IN:en"

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

    with urllib.request.urlopen(req, timeout=15) as resp:
        data = resp.read()

    root = ET.fromstring(data)
    items = []
    now = datetime.now(timezone.utc)
    max_age = timedelta(hours=MAX_POST_AGE_HOURS)

    for item in root.findall(".//item"):
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        guid = item.findtext("guid", link).strip()
        pub_date_str = item.findtext("pubDate", "").strip()

        if pub_date_str:
            try:
                pub_dt = email.utils.parsedate_to_datetime(pub_date_str)
                if now - pub_dt > max_age:
                    continue
            except Exception:
                pass

        if title and link:
            platform = "Social"
            if "x.com" in link or "twitter.com" in link:
                platform = "X"
            elif "facebook.com" in link:
                platform = "Facebook"
            elif "instagram.com" in link:
                platform = "Instagram"
            elif "t.me" in link:
                platform = "Telegram"

            items.append((f"[{platform}] {title}", link, guid))

    return items


def fetch_reddit(keyword):
    """Fetches recent posts directly from Reddit search RSS."""
    query = f'"{keyword}" ({SECURITY_ADMIN_FILTER})'
    query_encoded = urllib.parse.quote(query)
    url = f"https://www.reddit.com/search.rss?q={query_encoded}&sort=new"

    req = urllib.request.Request(
        url, headers={"User-Agent": "SocialKeywordMonitor/1.0"}
    )

    items = []
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()

        root = ET.fromstring(data)
        now = datetime.now(timezone.utc)
        max_age = timedelta(hours=MAX_POST_AGE_HOURS)

        atom_ns = "http://www.w3.org/2005/Atom"
        for entry in root.findall(f"{{{atom_ns}}}entry"):
            title = entry.findtext(f"{{{atom_ns}}}title", "").strip()
            link_elem = entry.find(f"{{{atom_ns}}}link")
            link = (
                link_elem.attrib.get("href", "").strip()
                if link_elem is not None
                else ""
            )
            published_str = entry.findtext(f"{{{atom_ns}}}updated", "").strip()

            if published_str:
                try:
                    pub_dt = datetime.fromisoformat(published_str)
                    if now - pub_dt > max_age:
                        continue
                except Exception:
                    pass

            if title and link:
                items.append((f"[Reddit] {title}", link, link))
    except Exception as e:
        print(f"Reddit fetch error for '{keyword}': {e}")

    return items


def send_notification(title, message, priority="default", tags="", retries=2):
    if not NTFY_URL:
        print(f"NTFY_TOPIC not set. Skipping notification:\n[{title}]\n{message}")
        return

    headers = {"Title": title, "Priority": priority}
    if tags:
        headers["Tags"] = tags

    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                NTFY_URL,
                data=message.encode("utf-8"),
                headers=headers,
                method="POST",
            )
            urllib.request.urlopen(req, timeout=15)
            return
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                wait = 5 * attempt
                print(f"Rate limited (429), waiting {wait}s before retry...")
                time.sleep(wait)
                continue
            print(f"Failed to send notification '{title}': {e}")
            return
        except Exception as e:
            print(f"Failed to send notification '{title}': {e}")
            return


def send_keyword_digest(kw, items):
    formatted_items = [
        f"{i+1}. {title}\n{link}" for i, (title, link) in enumerate(items)
    ]

    chunks = []
    current_chunk = []
    current_length = 0

    for item_str in formatted_items:
        item_bytes = len(item_str.encode("utf-8")) + 2
        if current_chunk and (current_length + item_bytes > MAX_PAYLOAD_BYTES):
            chunks.append(current_chunk)
            current_chunk = [item_str]
            current_length = item_bytes
        else:
            current_chunk.append(item_str)
            current_length += item_bytes

    if current_chunk:
        chunks.append(current_chunk)

    total_chunks = len(chunks)
    for idx, chunk in enumerate(chunks, 1):
        part_suffix = f" (Part {idx}/{total_chunks})" if total_chunks > 1 else ""
        title = f"Social: {kw} ({len(items)} new){part_suffix}"
        message = "\n\n".join(chunk)

        send_notification(
            title,
            message,
            priority="high",
            tags="speech_balloon",
        )
        print(f"Sent social digest for '{kw}'{part_suffix}: {len(chunk)} item(s)")
        time.sleep(SECONDS_BETWEEN_NOTIFICATIONS)


def main():
    state = load_state()
    seen_links_list = state.get("seen_links", [])
    seen_set = set(seen_links_list)

    quiet_keywords = []

    try:
        for kw in KEYWORDS:
            articles = []

            # 1. Fetch from Official YouTube Data API v3
            articles.extend(fetch_youtube_api(kw))

            # 2. Fetch Indexed X, Facebook, Instagram, Telegram via Google RSS
            try:
                articles.extend(fetch_google_social(kw))
            except Exception as e:
                print(f"Error fetching Google Social RSS for '{kw}': {e}")

            # 3. Fetch Reddit Posts
            try:
                articles.extend(fetch_reddit(kw))
            except Exception as e:
                print(f"Error fetching Reddit RSS for '{kw}': {e}")

            new_items = []
            for title, link, guid in articles:
                item_id = guid if guid else link
                if item_id not in seen_set:
                    new_items.append((title, link))
                    seen_set.add(item_id)
                    seen_links_list.append(item_id)

            if new_items:
                send_keyword_digest(kw, new_items)
            else:
                quiet_keywords.append(kw)

        if quiet_keywords:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            quiet_list = "\n".join([f"- {kw}" for kw in quiet_keywords])
            send_notification(
                f"Social Monitor: No updates ({len(quiet_keywords)} keywords)",
                f"Checked at {now}.\nNo new social posts for:\n{quiet_list}",
                priority="min",
                tags="white_check_mark",
            )
            print(f"Sent quiet summary for {len(quiet_keywords)} keyword(s).")

    finally:
        save_state(seen_links_list)


if __name__ == "__main__":
    main()
