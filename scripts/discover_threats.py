import json
import os
import re
import requests
from datetime import datetime, timezone

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
LLM_MODEL = "meta-llama/llama-3.1-8b-instruct:free"
VERIFIED_PATH = 'data/verified_threats.json'

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
  "title": "Kort dansk titel til truslen (max 80 tegn)",
  "short_desc": "2-3 sætninger på dansk der beskriver angrebet",
  "is_new_source": true/false
}}

Søgeresultat:
Titel: {title}
URL: {url}
Beskrivelse: {description}"""


def load_existing_links():
    if not os.path.exists(VERIFIED_PATH):
        return set()
    with open(VERIFIED_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return {entry.get('link', '') for entry in data}


def load_known_domains():
    """Load domains we already track via RSS feeds."""
    collect_path = os.path.join(
        os.path.dirname(__file__), 'collect_web.py'
    )
    known = set()
    try:
        with open(collect_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # Extract domains from feed URLs
        for match in re.findall(r'https?://([^/"\s]+)', content):
            known.add(match.lower().replace('www.', ''))
    except FileNotFoundError:
        pass
    return known


def brave_search(query, api_key, count=10):
    try:
        resp = requests.get(
            BRAVE_SEARCH_URL,
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


def classify_result(result, openrouter_key):
    prompt = CLASSIFY_PROMPT.format(
        title=result.get('title', ''),
        url=result.get('url', ''),
        description=result.get('description', '')[:500],
    )

    try:
        resp = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {openrouter_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": LLM_MODEL,
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

    if not brave_key:
        print("BRAVE_API_KEY not set — cannot discover threats")
        return

    if not openrouter_key:
        print("OPENROUTER_API_KEY not set — cannot classify results")
        return

    existing_links = load_existing_links()
    known_domains = load_known_domains()
    year = datetime.now().year

    # Select a subset of queries (rotate by day of year)
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
        results = brave_search(query, brave_key)

        for result in results:
            url = result.get('url', '')
            if not url or url in seen_urls or url in existing_links:
                continue
            seen_urls.add(url)

            print(f"  Classifying: {result['title'][:60]}...")
            classification = classify_result(result, openrouter_key)

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
                "explanation": classification.get("short_desc", ""),
                "discovered_via": "brave_search",
            }
            all_results.append(entry)

            if is_new_domain and classification.get("is_dk_attack"):
                new_source_domains.add(domain)

    # Save discovered threats
    os.makedirs("data/raw", exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    path = f"data/raw/discover_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    attacks = sum(1 for r in all_results if r.get("is_dk_attack"))
    print(f"Discovered {len(all_results)} results, "
          f"{attacks} verified DK attacks → {path}")

    # Save new source candidates for the source discovery workflow
    if new_source_domains:
        candidates_path = "data/raw/new_source_candidates.json"
        candidates = list(new_source_domains)
        with open(candidates_path, "w", encoding="utf-8") as f:
            json.dump(candidates, f, ensure_ascii=False, indent=2)
        print(f"Found {len(candidates)} new source candidates: "
              f"{', '.join(candidates)}")


if __name__ == '__main__':
    discover()
