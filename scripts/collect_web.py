import feedparser
import glob
import json
import os
import re
import requests
from datetime import datetime, timezone

FEEDS_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'data', 'feeds.json'
)
ENTITIES_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'data', 'danish_entities.json'
)
VERIFIED_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'data', 'verified_threats.json'
)
RAW_DIR = os.path.join(
    os.path.dirname(__file__), '..', 'data', 'raw'
)

CLASSIFY_PROMPT = """Du er en dansk cybersikkerhedsanalytiker.
Vurder om denne nyhed handler om et KONKRET cyberangreb, databrud \
eller sikkerhedshændelse der DIREKTE rammer Danmark \
(danske virksomheder, dansk infrastruktur, danske borgeres data).

VIGTIGT — disse tæller IKKE som danske angreb:
- Generelle sårbarhedsadvarsler (CVE, patches, 0-dage) uden dansk offer
- Globale trusler der ikke specifikt nævner danske mål
- Sikkerhedstips, guides, eller nyhedsopsummeringer

Svar KUN med denne JSON (ingen anden tekst):
{{
  "is_dk_attack": true/false,
  "confidence": "high"/"medium"/"low",
  "explanation": "1-2 sætninger på dansk der forklarer hvorfor"
}}

Nyhed:
Titel: {title}
Resumé: {summary}
Kilde: {source}"""


def load_feeds():
    """Load RSS feed URLs from the shared feeds.json file."""
    with open(FEEDS_PATH, 'r', encoding='utf-8') as f:
        feeds_data = json.load(f)
    return [feed['url'] for feed in feeds_data]


def load_known_links():
    """Load all URLs already in verified_threats.json and existing raw files."""
    known = set()

    if os.path.exists(VERIFIED_PATH):
        with open(VERIFIED_PATH, 'r', encoding='utf-8') as f:
            try:
                for entry in json.load(f):
                    link = entry.get('link', '')
                    if link:
                        known.add(link)
            except json.JSONDecodeError:
                pass

    if os.path.exists(RAW_DIR):
        for raw_file in glob.glob(os.path.join(RAW_DIR, '*.json')):
            try:
                with open(raw_file, 'r', encoding='utf-8') as f:
                    for entry in json.load(f):
                        if isinstance(entry, dict):
                            link = entry.get('link', '')
                            if link:
                                known.add(link)
            except (json.JSONDecodeError, TypeError):
                pass

    return known


def load_danish_patterns():
    with open(ENTITIES_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    terms = (
        data.get('companies', [])
        + data.get('government_and_infrastructure', [])
        + data.get('keywords', [])
    )
    escaped = [re.escape(t) for t in terms]
    pattern = re.compile('|'.join(escaped), re.IGNORECASE)
    return pattern


def keyword_prefilter(entry, pattern):
    text = ' '.join([
        entry.get('title', ''),
        entry.get('summary', ''),
    ])
    return bool(pattern.search(text))


def classify_with_llm(entry, api_key, api_url, model):
    prompt = CLASSIFY_PROMPT.format(
        title=entry.get('title', ''),
        summary=entry.get('summary', '')[:500],
        source=entry.get('source', ''),
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
                "max_tokens": 200,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]

        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r'^```\w*\n?', '', content)
            content = re.sub(r'\n?```$', '', content)

        result = json.loads(content)
        return {
            "is_dk_attack": bool(result.get("is_dk_attack", False)),
            "confidence": result.get("confidence", "low"),
            "explanation": result.get("explanation", ""),
        }
    except (requests.RequestException, json.JSONDecodeError,
            KeyError, IndexError) as e:
        print(f"  LLM classification failed: {e}")
        return {
            "is_dk_attack": False,
            "confidence": "error",
            "explanation": f"Klassificering fejlede: {e}",
        }


def collect():
    feeds = load_feeds()
    pattern = load_danish_patterns()
    known_links = load_known_links()
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    api_url = (os.environ.get("LLM_API_URL")
               or "https://openrouter.ai/api/v1/chat/completions")
    model = os.environ.get("LLM_MODEL_CHEAP", "")
    threats = []
    attack_count = 0
    skipped_dupes = 0

    for url in feeds:
        feed = feedparser.parse(url)
        for entry in feed.entries[:5]:
            link = entry.get("link", "")

            if link in known_links:
                skipped_dupes += 1
                continue

            item = {
                "title": entry.get("title", ""),
                "link": link,
                "published": entry.get("published", ""),
                "summary": entry.get("summary", ""),
                "source": url,
                "collected_at": datetime.now(timezone.utc).isoformat(),
            }

            has_dk_keyword = keyword_prefilter(item, pattern)

            if not has_dk_keyword:
                item["is_dk_attack"] = False
                item["confidence"] = "high"
                item["explanation"] = (
                    "Ingen danske nøgleord fundet i titel/resumé."
                )
            elif not api_key or not model:
                item["is_dk_attack"] = has_dk_keyword
                item["confidence"] = "keyword-only"
                item["explanation"] = (
                    "Nøgleordsmatch (ingen LLM-nøgle tilgængelig)."
                )
            else:
                print(f"  Classifying: {item['title'][:60]}...")
                result = classify_with_llm(item, api_key, api_url, model)
                item["is_dk_attack"] = result["is_dk_attack"]
                item["confidence"] = result["confidence"]
                item["explanation"] = result["explanation"]

            if item["is_dk_attack"]:
                attack_count += 1
            threats.append(item)
            known_links.add(link)

    os.makedirs("data/raw", exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    path = f"data/raw/web_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(threats, f, ensure_ascii=False, indent=2)

    total = len(threats)
    print(f"Saved {total} items to {path} "
          f"({attack_count} verified DK attacks, "
          f"{total - attack_count} filtered, "
          f"{skipped_dupes} duplicates skipped)")


if __name__ == "__main__":
    collect()
