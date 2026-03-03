import json
import os
import hashlib
import glob
import requests
from datetime import datetime, timedelta, timezone
from dateutil import parser as dateparser
from llm_utils import extract_json

VERIFIED_PATH = 'data/verified_threats.json'
RAW_DIR = 'data/daily'
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

DEDUP_PROMPT = """Du er en dansk cybersikkerhedsanalytiker.
Sammenlign nye artikler med EKSISTERENDE verificerede trusler.

En ny artikel er en DUPLIKAT hvis den handler om PRÆCIS SAMME \
hændelse/angreb som en eksisterende trussel OG tidspunkterne er \
tæt på hinanden (inden for 14 dage).

EKSISTERENDE verificerede trusler:
{existing}

NYE artikler:
{new_articles}

Returnér KUN denne JSON (ingen anden tekst):
{{
  "duplicates": [
    {{
      "new_index": 0,
      "existing_id": "abc123",
      "reason": "Kort forklaring"
    }}
  ]
}}

Regler:
- Kun marker som duplikat hvis det TYDELIGT er SAMME hændelse
- Forskellige angreb mod samme sektor er IKKE duplikater
- Artikler der tilføjer NY info om en eksisterende hændelse ER \
duplikater (de skal tilføjes som ekstra kilde)
- Returnér tom liste hvis ingen duplikater: {{"duplicates": []}}"""


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
        result = extract_json(content)
        if result is None:
            print(f"  LLM returned unparseable content: {content[:200]}")
            return [{"indices": [i]} for i in range(len(new_entries))]

        # LLM may return {"groups": [...]} or just [...]
        if isinstance(result, list):
            raw_groups = result
        else:
            raw_groups = result.get("groups", [])

        groups = []
        for group in raw_groups:
            indices = group.get("indices", [])
            if indices:
                groups.append({
                    "indices": indices,
                    "name": group.get("name", ""),
                    "description": group.get("description", ""),
                })
        return groups

    except (requests.RequestException, KeyError, IndexError) as e:
        print(f"  LLM merge failed: {e} — keeping entries separate")
        return [{"indices": [i]} for i in range(len(new_entries))]


def dedup_against_verified(new_entries, verified, api_key, api_url,
                           model):
    """Check new entries against existing verified threats by subject+time.

    Returns:
        kept: list of new_entries that are NOT duplicates
        to_augment: list of (new_entry, existing_id) for entries that
                    should be added as additional sources to existing threats
    """
    if not new_entries or not verified or not api_key or not model:
        return new_entries, []

    # Only compare against recent threats (last 30 days)
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=30)
                   ).strftime('%Y-%m-%d')
    recent = [v for v in verified
              if v.get('timestamp', '') >= cutoff_date]

    # If fewer than 30 recent, expand window
    if len(recent) < len(verified):
        sorted_v = sorted(verified,
                          key=lambda x: x.get('timestamp', ''),
                          reverse=True)
        recent = sorted_v[:30]

    if not recent:
        return new_entries, []

    # Build context for LLM
    existing_text = ""
    for v in recent:
        existing_text += (
            f"[ID: {v['id']}] {v['name']}\n"
            f"  Dato: {v.get('timestamp', '')}\n"
            f"  Type: {v.get('attack_type', '')}\n"
            f"  Beskrivelse: {v.get('description', '')[:100]}\n\n"
        )

    new_text = ""
    for i, entry in enumerate(new_entries):
        new_text += (
            f"[{i}] Titel: {entry.get('title', '')}\n"
            f"    Dato: {entry.get('published', '')}\n"
            f"    Type: {entry.get('attack_type', '')}\n"
            f"    Resumé: {entry.get('summary', '')[:100]}\n\n"
        )

    prompt = DEDUP_PROMPT.format(
        existing=existing_text,
        new_articles=new_text,
    )

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
                "max_tokens": 500,
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        result = extract_json(content)
        if result is None:
            print(f"  Dedup LLM unparseable: {content[:200]}")
            return new_entries, []

        duplicates = result.get("duplicates", [])
        if not duplicates:
            print("  Cross-dedup: no duplicates found")
            return new_entries, []

        # Build sets
        dup_indices = set()
        to_augment = []
        for dup in duplicates:
            idx = dup.get("new_index")
            eid = dup.get("existing_id", "")
            reason = dup.get("reason", "")
            if idx is not None and 0 <= idx < len(new_entries):
                dup_indices.add(idx)
                to_augment.append((new_entries[idx], eid))
                print(f"  Cross-dedup: [{idx}] matches "
                      f"existing {eid} — {reason}")

        kept = [e for i, e in enumerate(new_entries)
                if i not in dup_indices]
        print(f"  Cross-dedup: {len(dup_indices)} duplicates, "
              f"{len(kept)} kept")
        return kept, to_augment

    except (requests.RequestException, KeyError, IndexError) as e:
        print(f"  Cross-dedup failed: {e} — keeping all entries")
        return new_entries, []


def augment_existing_threats(verified, to_augment):
    """Add duplicate entries as additional sources to existing threats."""
    if not to_augment:
        return 0

    threats_by_id = {e.get('id'): e for e in verified}
    augmented = 0

    for entry, existing_id in to_augment:
        threat = threats_by_id.get(existing_id)
        if not threat:
            continue

        new_url = entry.get('link', '')
        if not new_url:
            continue

        # Check not already in sources
        all_urls = {threat.get('link', '')}
        for src in threat.get('additional_sources', []):
            all_urls.add(src.get('url', ''))

        if new_url in all_urls:
            continue

        source = source_name(entry.get('source', ''))
        threat.setdefault('additional_sources', []).append(
            {"url": new_url, "name": source}
        )
        augmented += 1

    return augmented


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
        print("No raw files found in data/daily/ - nothing to append")
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

            if not entry.get('is_dk_relevant', False):
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

    # Cross-dedup: check new entries against existing verified threats
    # by subject + time before within-batch merging
    cross_dedup_count = 0
    if api_key and model and verified:
        print(f"Cross-dedup: checking {len(new_entries)} entries "
              f"against {len(verified)} verified threats...")
        new_entries, to_augment = dedup_against_verified(
            new_entries, verified, api_key, api_url, model)
        cross_dedup_count = len(to_augment)
        if to_augment:
            aug = augment_existing_threats(verified, to_augment)
            print(f"  Augmented {aug} existing threats "
                  f"with new sources")

    if not new_entries:
        if cross_dedup_count:
            save_verified(verified)
            print(f"All new entries were duplicates of existing "
                  f"threats ({cross_dedup_count} augmented)")
        else:
            print(f"No new DK attacks to append "
                  f"(skipped {skipped_irrelevant} non-DK-relevant)")
        return

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
    dedup_msg = ""
    if cross_dedup_count:
        dedup_msg = (f", cross-dedup {cross_dedup_count} "
                     f"matched existing")
    print(f"Appended {merged_count} threats from {source_count} sources "
          f"(total: {len(verified)}, "
          f"skipped {skipped_irrelevant} non-DK-relevant, "
          f"merged {source_count - merged_count} duplicates"
          f"{dedup_msg})")


if __name__ == '__main__':
    append_verified()
