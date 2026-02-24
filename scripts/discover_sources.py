import json
import os
import feedparser
import requests
from datetime import datetime, timezone

CANDIDATES_PATH = 'data/raw/new_source_candidates.json'
FEEDS_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'data', 'feeds.json'
)

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
                    "url": url,
                    "name": title,
                    "language": "da",
                    "added": datetime.now(timezone.utc).strftime('%Y-%m-%d'),
                    "added_by": "discovery",
                    "domain": domain,
                    "entry_count": len(feed.entries),
                    "sample_title": feed.entries[0].get('title', ''),
                }
        except requests.RequestException:
            continue

    return None


def load_feeds():
    """Load current feeds from feeds.json."""
    if not os.path.exists(FEEDS_PATH):
        return []
    with open(FEEDS_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_feeds(feeds):
    """Save feeds to feeds.json."""
    with open(FEEDS_PATH, 'w', encoding='utf-8') as f:
        json.dump(feeds, f, ensure_ascii=False, indent=2)


def extract_domain(url):
    """Extract domain from feed URL."""
    import re
    match = re.match(r'https?://(?:www\.)?([^/]+)', url)
    return match.group(1).lower() if match else ""


def discover_sources():
    if not os.path.exists(CANDIDATES_PATH):
        print("No new source candidates found — nothing to check")
        return

    with open(CANDIDATES_PATH, 'r', encoding='utf-8') as f:
        candidates = json.load(f)

    if not candidates:
        print("Empty candidates list — nothing to check")
        return

    # Load existing feeds to avoid duplicates
    existing_feeds = load_feeds()
    existing_domains = set()
    for feed in existing_feeds:
        domain = extract_domain(feed.get('url', ''))
        if domain:
            existing_domains.add(domain)

    discovered = []
    for domain in candidates:
        if domain in existing_domains:
            print(f"  Already tracked: {domain}")
            continue

        print(f"  Probing {domain} for RSS feeds...")
        result = try_find_feed(domain)
        if result:
            print(f"    Found: {result['url']} "
                  f"({result['entry_count']} entries)")
            discovered.append(result)
        else:
            print(f"    No feed found for {domain}")

    if not discovered:
        print("No new feeds discovered")
        os.remove(CANDIDATES_PATH)
        return

    # Append new feeds directly to feeds.json
    for feed in discovered:
        # Remove temporary fields before saving
        clean_feed = {
            "url": feed["url"],
            "name": feed["name"],
            "language": feed["language"],
            "added": feed["added"],
            "added_by": feed["added_by"],
        }
        existing_feeds.append(clean_feed)

    save_feeds(existing_feeds)

    # Clean up candidates
    os.remove(CANDIDATES_PATH)

    print(f"Added {len(discovered)} new feeds to feeds.json:")
    for feed in discovered:
        print(f"  {feed['domain']}: {feed['url']}")


if __name__ == '__main__':
    discover_sources()
