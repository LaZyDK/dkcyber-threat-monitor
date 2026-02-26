import json
import os
import re
import requests
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
VERIFIED_PATH = os.path.join(DATA_DIR, 'verified_threats.json')
FEEDS_PATH = os.path.join(DATA_DIR, 'feeds.json')
LEDGER_PATH = os.path.join(DATA_DIR, 'analyzed_urls.json')
RAW_DIR = os.path.join(DATA_DIR, 'raw')

# Rotating search queries — Danish cyber attacks from multiple angles
SEARCH_QUERIES = [
    "cyberangreb Danmark {year}",
    "danish company hacked {year}",
    "ransomware Danmark {year}",
    "databrud dansk virksomhed {year}",
    "cyber attack Denmark {year}",
    "it-sikkerhed angreb dansk {year}",
    "hacking danske virksomheder {year}",
    "DDoS angreb Danmark {year}",
    "phishing kampagne Danmark {year}",
    "sikkerhedsbrud dansk infrastruktur {year}",
]

CLASSIFY_PROMPT = """Du er en dansk cybersikkerhedsanalytiker.
Vurder om dette søgeresultat handler om et KONKRET cyberangreb, \
databrud eller sikkerhedshændelse der DIREKTE rammer Danmark.

VIGTIGT — disse tæller IKKE:
- Generelle sårbarhedsadvarsler uden dansk offer
- Artikler om cybersikkerhed generelt (tips, guides, rapporter)
- Gamle kendte angreb (WannaCry, NotPetya) medmindre ny info
- Artikler der kun nævner Danmark i forbifarten

Svar KUN med denne JSON (ingen anden tekst):
{{
  "is_dk_attack": true/false,
  "confidence": "high"/"medium"/"low",
  "attack_type": "ransomware"/"ddos"/"phishing"/"databrud"/"supply-chain"/"andet"/"ukendt",
  "sector": "sundhed"/"finans"/"offentlig"/"energi"/"transport"/"telecom"/"uddannelse"/"detailhandel"/"it"/"andet"/"ukendt",
  "title": "Kort dansk titel til truslen (max 80 tegn)",
  "short_desc": "2-3 sætninger på dansk der beskriver angrebet",
  "is_new_source": true/false
}}

Søgeresultat:
Titel: {title}
URL: {url}
Beskrivelse: {description}"""


def load_ledger():
    """Load the analyzed URLs ledger."""
    if os.path.exists(LEDGER_PATH):
        try:
            with open(LEDGER_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return []


def save_ledger(ledger):
    """Save the analyzed URLs ledger."""
    with open(LEDGER_PATH, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)


def load_all_known_links():
    """Load all URLs from ledger and verified_threats.json."""
    known = set()

    if os.path.exists(VERIFIED_PATH):
        with open(VERIFIED_PATH, 'r', encoding='utf-8') as f:
            try:
                for entry in json.load(f):
                    link = entry.get('link', '')
                    if link:
                        known.add(link)
                    for src in entry.get('additional_sources', []):
                        url = src.get('url', '')
                        if url:
                            known.add(url)
            except json.JSONDecodeError:
                pass

    ledger = load_ledger()
    for entry in ledger:
        url = entry.get('url', '')
        if url:
            known.add(url)

    return known


def load_known_domains():
    """Load domains we already track via feeds.json."""
    known = set()
    try:
        with open(FEEDS_PATH, 'r', encoding='utf-8') as f:
            feeds = json.load(f)
        for feed in feeds:
            url = feed.get('url', '')
            match = re.match(r'https?://(?:www\.)?([^/]+)', url)
            if match:
                known.add(match.group(1).lower())
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return known


def brave_search(query, api_key, brave_url, count=10):
    try:
        resp = requests.get(
            brave_url,
            headers={"Accept": "application/json",
                     "Accept-Encoding": "gzip",
                     "X-Subscription-Token": api_key},
            params={"q": query, "count": count,
                    "search_lang": "da", "freshness": "pw"},
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("web", {}).get("results", [])
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "description": r.get("description", ""),
            }
            for r in results
        ]
    except requests.RequestException as e:
        print(f"  Brave search failed for '{query}': {e}")
        return []


def classify_result(result, openrouter_key, api_url, model):
    prompt = CLASSIFY_PROMPT.format(
        title=result.get('title', ''),
        url=result.get('url', ''),
        description=result.get('description', '')[:500],
    )

    try:
        resp = requests.post(
            api_url,
            headers={
                "Authorization": f"Bearer {openrouter_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 300,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r'^```\w*\n?', '', content)
            content = re.sub(r'\n?```$', '', content)

        return json.loads(content)
    except (requests.RequestException, json.JSONDecodeError,
            KeyError, IndexError) as e:
        print(f"  LLM classify failed: {e}")
        return {"is_dk_attack": False, "confidence": "error"}


def extract_domain(url):
    match = re.match(r'https?://(?:www\.)?([^/]+)', url)
    return match.group(1).lower() if match else ""


def discover():
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
    brave_key = os.environ.get("BRAVE_API_KEY", "")
    api_url = (os.environ.get("LLM_API_URL")
               or "https://openrouter.ai/api/v1/chat/completions")
    brave_url = (os.environ.get("BRAVE_SEARCH_URL")
                 or "https://api.search.brave.com/res/v1/web/search")
    model = os.environ.get("LLM_MODEL_CHEAP", "")

    if not brave_key:
        print("BRAVE_API_KEY not set — cannot discover threats")
        return

    if not openrouter_key or not model:
        print("OPENROUTER_API_KEY or LLM_MODEL_CHEAP not set — cannot classify")
        return

    existing_links = load_all_known_links()
    known_domains = load_known_domains()
    ledger = load_ledger()
    year = datetime.now().year

    day = datetime.now().timetuple().tm_yday
    queries_today = [
        SEARCH_QUERIES[i % len(SEARCH_QUERIES)]
        for i in range(day, day + 3)
    ]

    all_results = []
    seen_urls = set()
    new_source_domains = set()

    for query_template in queries_today:
        query = query_template.format(year=year)
        print(f"Searching: {query}")
        results = brave_search(query, brave_key, brave_url)

        for result in results:
            url = result.get('url', '')
            if not url or url in seen_urls or url in existing_links:
                continue
            seen_urls.add(url)

            print(f"  Classifying: {result['title'][:60]}...")
            classification = classify_result(
                result, openrouter_key, api_url, model)

            domain = extract_domain(url)
            is_new_domain = domain and domain not in known_domains

            entry = {
                "title": classification.get("title",
                                            result["title"])[:80],
                "link": url,
                "published": datetime.now(timezone.utc).strftime(
                    '%Y-%m-%d'),
                "summary": classification.get("short_desc",
                                              result["description"]),
                "source": f"discover:{domain}",
                "source_domain": domain,
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "is_dk_attack": classification.get("is_dk_attack",
                                                   False),
                "confidence": classification.get("confidence", "low"),
                "attack_type": classification.get("attack_type",
                                                   "ukendt"),
                "sector": classification.get("sector", "ukendt"),
                "explanation": classification.get("short_desc", ""),
                "discovered_via": "brave_search",
            }
            # If classified as DK attack but type is unknown, skip it
            if (entry["is_dk_attack"]
                    and entry.get("attack_type") == "ukendt"):
                entry["is_dk_attack"] = False
                entry["explanation"] += (
                    " Nedgraderet: angrebstype kunne ikke bestemmes.")

            all_results.append(entry)
            ledger.append({
                "url": url,
                "analyzed_at": entry["collected_at"],
                "is_dk_attack": entry["is_dk_attack"],
            })

            if is_new_domain and classification.get("is_dk_attack"):
                new_source_domains.add(domain)

    os.makedirs("data/raw", exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    path = f"data/raw/discover_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    save_ledger(ledger)

    attacks = sum(1 for r in all_results if r.get("is_dk_attack"))
    print(f"Discovered {len(all_results)} results, "
          f"{attacks} verified DK attacks → {path}")

    if new_source_domains:
        candidates_path = "data/raw/new_source_candidates.json"
        candidates = list(new_source_domains)
        with open(candidates_path, "w", encoding="utf-8") as f:
            json.dump(candidates, f, ensure_ascii=False, indent=2)
        print(f"Found {len(candidates)} new source candidates: "
              f"{', '.join(candidates)}")


if __name__ == '__main__':
    discover()
