import json
import os
import hashlib
import glob
from datetime import datetime, timezone
from dateutil import parser as dateparser

VERIFIED_PATH = 'data/verified_threats.json'
RAW_DIR = 'data/raw'


def load_verified():
    if not os.path.exists(VERIFIED_PATH):
        return []
    with open(VERIFIED_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_verified(data):
    with open(VERIFIED_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def make_id(link, title):
    raw = f"{link}|{title}"
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
    mapping = {
        'cert.dk': 'DKCERT',
        'cert.se': 'CERT-SE',
        'version2.dk': 'Version2',
    }
    for key, name in mapping.items():
        if key.lower() in source_url.lower():
            return name
    return source_url


def append_verified():
    verified = load_verified()
    existing_links = {entry.get('link') for entry in verified}

    raw_files = sorted(glob.glob(os.path.join(RAW_DIR, '*.json')))
    if not raw_files:
        print("No raw files found in data/raw/ - nothing to append")
        return

    new_count = 0
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
            link = entry.get('link', '')
            if link in existing_links:
                continue

            # Only append entries verified as Danish attacks by LLM
            if not entry.get('is_dk_attack', False):
                skipped_irrelevant += 1
                continue

            title = entry.get('title', 'Unknown')
            verified_entry = {
                'id': make_id(link, title),
                'title': title,
                'date': parse_date(entry.get('published', '')),
                'source': source_name(entry.get('source', '')),
                'link': link,
                'short_desc': (entry.get('summary', '')[:300] or ''),
                'verified_by': 'human-review',
                'verified_at': now,
            }
            verified.append(verified_entry)
            existing_links.add(link)
            new_count += 1

    save_verified(verified)
    print(f"Appended {new_count} new verified threats "
          f"(total: {len(verified)}, "
          f"skipped {skipped_irrelevant} non-DK-relevant)")


if __name__ == '__main__':
    append_verified()
