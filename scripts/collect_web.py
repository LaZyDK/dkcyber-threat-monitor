import feedparser
import json
import os
import re
from datetime import datetime, timezone

feeds = [
    "https://www.cert.dk/news/rss",       # DKCERT – dansk CERT
    "https://www.cert.se/feed.rss",        # CERT-SE – svensk CERT (nordisk)
    "https://www.version2.dk/rss",         # Version2 – dansk IT-nyheder
    # tilføj flere senere
]

ENTITIES_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'data', 'danish_entities.json'
)


def load_danish_patterns():
    with open(ENTITIES_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    terms = (
        data.get('companies', [])
        + data.get('government_and_infrastructure', [])
        + data.get('keywords', [])
    )
    # Escape regex special chars but keep it case-insensitive
    escaped = [re.escape(t) for t in terms]
    pattern = re.compile('|'.join(escaped), re.IGNORECASE)
    return pattern


def is_dk_relevant(entry, pattern):
    text = ' '.join([
        entry.get('title', ''),
        entry.get('summary', ''),
    ])
    return bool(pattern.search(text))


def collect():
    pattern = load_danish_patterns()
    threats = []
    relevant_count = 0

    for url in feeds:
        feed = feedparser.parse(url)
        for entry in feed.entries[:5]:  # begræns til nyeste
            item = {
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "summary": entry.get("summary", ""),
                "source": url,
                "collected_at": datetime.now(timezone.utc).isoformat(),
            }
            item["dk_relevant"] = is_dk_relevant(item, pattern)
            if item["dk_relevant"]:
                relevant_count += 1
            threats.append(item)

    os.makedirs("data/raw", exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    path = f"data/raw/web_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(threats, f, ensure_ascii=False, indent=2)

    total = len(threats)
    print(f"Saved {total} items to {path} "
          f"({relevant_count} DK-relevant, "
          f"{total - relevant_count} filtered)")


if __name__ == "__main__":
    collect()
