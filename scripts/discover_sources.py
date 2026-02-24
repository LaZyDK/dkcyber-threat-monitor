import json
import os
import feedparser
import requests

CANDIDATES_PATH = 'data/raw/new_source_candidates.json'
FEEDS_REGISTRY_PATH = 'data/discovered_feeds.json'

# Common RSS feed path patterns to try
FEED_PATHS = [
    '/rss', '/feed', '/rss.xml', '/feed.xml', '/atom.xml',
    '/feeds', '/news/rss', '/blog/rss', '/blog/feed',
    '/feed/rss', '/index.xml', '/rss/news',
]


def try_find_feed(domain):
    """Try common feed paths on a domain. Return first working one."""
    for path in FEED_PATHS:
        url = f"https://{domain}{path}"
        try:
            resp = requests.get(url, timeout=10,
                                allow_redirects=True,
                                headers={'User-Agent': 'dkcyber-bot/1.0'})
            if resp.status_code != 200:
                continue

            feed = feedparser.parse(resp.text)
            if feed.entries and len(feed.entries) > 0:
                title = feed.feed.get('title', domain)
                return {
                    "domain": domain,
                    "feed_url": url,
                    "feed_title": title,
                    "entry_count": len(feed.entries),
                    "sample_title": feed.entries[0].get('title', ''),
                }
        except requests.RequestException:
            continue

    return None


def discover_sources():
    if not os.path.exists(CANDIDATES_PATH):
        print("No new source candidates found — nothing to check")
        return

    with open(CANDIDATES_PATH, 'r', encoding='utf-8') as f:
        candidates = json.load(f)

    if not candidates:
        print("Empty candidates list — nothing to check")
        return

    # Load previously discovered feeds to avoid re-suggesting
    existing_feeds = set()
    if os.path.exists(FEEDS_REGISTRY_PATH):
        with open(FEEDS_REGISTRY_PATH, 'r', encoding='utf-8') as f:
            existing = json.load(f)
        existing_feeds = {e.get('domain') for e in existing}

    discovered = []
    for domain in candidates:
        if domain in existing_feeds:
            print(f"  Already known: {domain}")
            continue

        print(f"  Probing {domain} for RSS feeds...")
        result = try_find_feed(domain)
        if result:
            print(f"    Found: {result['feed_url']} "
                  f"({result['entry_count']} entries)")
            discovered.append(result)
        else:
            print(f"    No feed found for {domain}")

    if not discovered:
        print("No new feeds discovered")
        # Clean up candidates file
        os.remove(CANDIDATES_PATH)
        return

    # Save to registry
    all_feeds = []
    if os.path.exists(FEEDS_REGISTRY_PATH):
        with open(FEEDS_REGISTRY_PATH, 'r', encoding='utf-8') as f:
            all_feeds = json.load(f)
    all_feeds.extend(discovered)

    os.makedirs(os.path.dirname(FEEDS_REGISTRY_PATH) or '.', exist_ok=True)
    with open(FEEDS_REGISTRY_PATH, 'w', encoding='utf-8') as f:
        json.dump(all_feeds, f, ensure_ascii=False, indent=2)

    # Clean up candidates
    os.remove(CANDIDATES_PATH)

    print(f"Discovered {len(discovered)} new feeds:")
    for feed in discovered:
        print(f"  {feed['domain']}: {feed['feed_url']}")


if __name__ == '__main__':
    discover_sources()
