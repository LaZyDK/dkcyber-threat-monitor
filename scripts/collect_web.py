import feedparser
import json
import os
import re
import requests
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

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
LLM_MODEL = "meta-llama/llama-3.3-70b-instruct:free"

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


def classify_with_llm(entry, api_key):
    prompt = CLASSIFY_PROMPT.format(
        title=entry.get('title', ''),
        summary=entry.get('summary', '')[:500],
        source=entry.get('source', ''),
    )

    try:
        resp = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 200,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]

        # Extract JSON from response (handle markdown code blocks)
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
    pattern = load_danish_patterns()
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    threats = []
    attack_count = 0

    for url in feeds:
        feed = feedparser.parse(url)
        for entry in feed.entries[:5]:
            item = {
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "summary": entry.get("summary", ""),
                "source": url,
                "collected_at": datetime.now(timezone.utc).isoformat(),
            }

            # Stage 1: fast keyword pre-filter
            has_dk_keyword = keyword_prefilter(item, pattern)

            if not has_dk_keyword:
                # No Danish keywords at all — skip LLM call
                item["is_dk_attack"] = False
                item["confidence"] = "high"
                item["explanation"] = (
                    "Ingen danske nøgleord fundet i titel/resumé."
                )
            elif not api_key:
                # No API key — fall back to keyword match only
                item["is_dk_attack"] = has_dk_keyword
                item["confidence"] = "keyword-only"
                item["explanation"] = (
                    "Nøgleordsmatch (ingen LLM-nøgle tilgængelig)."
                )
            else:
                # Stage 2: LLM verifies if it's a real Danish attack
                print(f"  Classifying: {item['title'][:60]}...")
                result = classify_with_llm(item, api_key)
                item["is_dk_attack"] = result["is_dk_attack"]
                item["confidence"] = result["confidence"]
                item["explanation"] = result["explanation"]

            if item["is_dk_attack"]:
                attack_count += 1
            threats.append(item)

    os.makedirs("data/raw", exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    path = f"data/raw/web_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(threats, f, ensure_ascii=False, indent=2)

    total = len(threats)
    print(f"Saved {total} items to {path} "
          f"({attack_count} verified DK attacks, "
          f"{total - attack_count} filtered)")


if __name__ == "__main__":
    collect()
