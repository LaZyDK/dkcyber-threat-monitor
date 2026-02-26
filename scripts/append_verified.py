import json
import os
import hashlib
import glob
import re
import requests
from datetime import datetime, timezone
from dateutil import parser as dateparser

VERIFIED_PATH = 'data/verified_threats.json'
RAW_DIR = 'data/daily/raw'
NEWLY_ADDED_PATH = 'data/daily/newly_added.json'
FEEDS_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'data', 'feeds.json'
)

MERGE_PROMPT = """Du er en dansk cybersikkerhedsanalytiker.
Nedenstående er en liste af nyhedsartikler om cyberangreb i Danmark.
Grupper dem efter HVILKET ANGREB de handler om.

Flere artikler fra forskellige medier kan handle om DET SAMME angreb.
Gruppér dem sammen.

Returnér KUN denne JSON (ingen anden tekst):
{{
  "groups": [
    {{
      "name": "Bedste danske titel til angrebet (max 80 tegn)",
      "description": "2-3 sætninger om angrebet",
      "indices": [0, 3, 5]
    }}
  ]
}}

Regler:
- "indices" er 0-baserede indekser fra listen nedenfor
- Hver artikel SKAL optræde i præcis én gruppe
- Artikler om FORSKELLIGE angreb skal IKKE grupperes
- Artikler om SAMME hændelse fra forskellige medier SKAL grupperes

Artikler:
{articles}"""


def load_verified():
    if not os.path.exists(VERIFIED_PATH):
        return []
    with open(VERIFIED_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_verified(data):
    with open(VERIFIED_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def make_id(link, name):
    raw = f"{link}|{name}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def parse_date(published_str):
    if not published_str:
        return datetime.now(timezone.utc).strftime('%Y-%m-%d')
    try:
        dt = dateparser.parse(published_str)
        return dt.strftime('%Y-%m-%d')
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def source_name(source_url):
    """Map source URLs to human-readable names using feeds.json."""
    try:
        with open(FEEDS_PATH, 'r', encoding='utf-8') as f:
            feeds = json.load(f)
        for feed in feeds:
            if feed.get('url', '') == source_url:
                return feed.get('name', source_url)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # For discover: sources, extract the domain
    if source_url.startswith('discover:'):
        return source_url.replace('discover:', '')

    return source_url


def merge_with_llm(new_entries, api_key, api_url, model):
    """Use LLM to group entries about the same attack."""
    if len(new_entries) <= 1 or not api_key or not model:
        return [{"indices": [i]} for i in range(len(new_entries))]

    articles = []
    for i, entry in enumerate(new_entries):
        articles.append(
            f"[{i}] Titel: {entry.get('title', '')}\n"
            f"    Kilde: {entry.get('source', '')}\n"
            f"    Resumé: {entry.get('summary', '')}"
        )

    prompt = MERGE_PROMPT.format(articles="\n".join(articles))

    try:
        resp = requests.post(
            api_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 1000,
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r'^```\w*\n?', '', content)
            content = re.sub(r'\n?```$', '', content)

        result = json.loads(content)
        groups = []
        for group in result.get("groups", []):
            indices = group.get("indices", [])
            if indices:
                groups.append({
                    "indices": indices,
                    "name": group.get("name", ""),
                    "description": group.get("description", ""),
                })
        return groups

    except (requests.RequestException, json.JSONDecodeError,
            KeyError, IndexError) as e:
        print(f"  LLM merge failed: {e} — keeping entries separate")
        return [{"indices": [i]} for i in range(len(new_entries))]


def build_merged_entry(group, new_entries, now):
    """Build a single verified entry from a group of related entries."""
    indices = group["indices"]
    primary = new_entries[indices[0]]

    name = group.get("name") or primary.get('title', 'Unknown')
    description = group.get("description") or (primary.get('summary', '') or '')

    all_sources = []
    earliest_date = None

    for idx in indices:
        entry = new_entries[idx]
        link = entry.get('link', '')
        source = source_name(entry.get('source', ''))
        date = parse_date(entry.get('published', ''))

        if link:
            all_sources.append({"url": link, "name": source})
        if earliest_date is None or date < earliest_date:
            earliest_date = date

    primary_link = all_sources[0]["url"] if all_sources else ''
    primary_source = all_sources[0]["name"] if all_sources else ''

    verified_entry = {
        'id': make_id(primary_link, name),
        'name': name[:80],
        'description': description,
        'attack_type': primary.get('attack_type', 'ukendt'),
        'sector': primary.get('sector', 'ukendt'),
        'source': primary_source,
        'link': primary_link,
        'additional_sources': all_sources[1:] if len(all_sources) > 1
        else [],
        'timestamp': earliest_date or datetime.now(timezone.utc).strftime(
            '%Y-%m-%d'),
        'verified_by': 'human-review',
        'verified_at': now,
    }

    return verified_entry


def append_verified():
    verified = load_verified()
    existing_links = set()
    for entry in verified:
        existing_links.add(entry.get('link', ''))
        for src in entry.get('additional_sources', []):
            existing_links.add(src.get('url', ''))

    raw_files = sorted(glob.glob(os.path.join(RAW_DIR, '*.json')))
    if not raw_files:
        print("No raw files found in data/daily/raw/ - nothing to append")
        return

    new_entries = []
    skipped_irrelevant = 0
    now = datetime.now(timezone.utc).isoformat()

    for raw_file in raw_files:
        with open(raw_file, 'r', encoding='utf-8') as f:
            try:
                entries = json.load(f)
            except json.JSONDecodeError:
                print(f"Skipping invalid JSON: {raw_file}")
                continue

        for entry in entries:
            if not isinstance(entry, dict):
                print(f"Skipping non-dict entry in {raw_file}: {entry}")
                continue
            link = entry.get('link', '')
            if link in existing_links:
                continue

            if not entry.get('is_dk_attack', False):
                skipped_irrelevant += 1
                continue

            new_entries.append(entry)
            existing_links.add(link)

    if not new_entries:
        print(f"No new DK attacks to append "
              f"(skipped {skipped_irrelevant} non-DK-relevant)")
        return

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    api_url = (os.environ.get("LLM_API_URL")
               or "https://openrouter.ai/api/v1/chat/completions")
    model = os.environ.get("LLM_MODEL_CHEAP", "")

    if len(new_entries) > 1 and api_key and model:
        print(f"Merging {len(new_entries)} entries...")
        groups = merge_with_llm(new_entries, api_key, api_url, model)
    else:
        groups = [{"indices": [i]} for i in range(len(new_entries))]

    merged_count = 0
    newly_added_ids = []
    for group in groups:
        merged_entry = build_merged_entry(group, new_entries, now)
        verified.append(merged_entry)
        newly_added_ids.append(merged_entry['id'])
        merged_count += 1

    save_verified(verified)

    # Write newly added IDs so post_to_reddit.py knows which threats to post
    os.makedirs(os.path.dirname(NEWLY_ADDED_PATH), exist_ok=True)
    with open(NEWLY_ADDED_PATH, 'w', encoding='utf-8') as f:
        json.dump(newly_added_ids, f, ensure_ascii=False, indent=2)

    source_count = len(new_entries)
    print(f"Appended {merged_count} threats from {source_count} sources "
          f"(total: {len(verified)}, "
          f"skipped {skipped_irrelevant} non-DK-relevant, "
          f"merged {source_count - merged_count} duplicates)")


if __name__ == '__main__':
    append_verified()
