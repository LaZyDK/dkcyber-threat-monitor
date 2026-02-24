import feedparser
import json
import os
from datetime import datetime, timezone

feeds = [
    "https://feeds.feedburner.com/TalosBlog",
    "https://www.darkreading.com/rss.xml",
    # tilføj flere senere
]

def collect():
    threats = []
    for url in feeds:
        feed = feedparser.parse(url)
        for entry in feed.entries[:5]:  # begræns til nyeste
            threats.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "summary": entry.get("summary", ""),
                "source": url,
                "collected_at": datetime.now(timezone.utc).isoformat()
            })

    os.makedirs("data/raw", exist_ok=True)
    path = f"data/raw/web_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(threats, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(threats)} items to {path}")

if __name__ == "__main__":
    collect()