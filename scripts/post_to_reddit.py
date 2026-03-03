import praw
import json
import os
import re
import subprocess
import sys
import glob
import requests
from llm_utils import extract_json


VERIFIED_PATH = 'data/verified_threats.json'
NEWLY_ADDED_PATH = 'data/daily/newly_added.json'

MONTHLY_PROMPT = """Du er en dansk cybersecurity-entusiast \
der poster i r/dkcybersecurity.
Skriv en engagerende, naturlig månedlig opsummering på dansk. Emojis sparsomt.

VIGTIGT – brug en markdown-tabel med disse kolonner:
Dato | Hændelse | Type | Sektor | Beskrivelse | Kilde | Diskussion

Hvor:
- Dato = timestamp
- Hændelse = navn på angrebet
- Type = angrebstype (ransomware, DDoS, phishing, databrud, etc.)
- Sektor = berørt sektor (sundhed, finans, offentlig, etc.)
- Beskrivelse = kort beskrivelse
- Kilde = markdown-link [kilde](url)
- Diskussion = hvis reddit_url findes, link til Reddit-tråd [tråd](reddit_url). \
Ellers skriv '-'.

Fremhæv trends: er der mønstre i angrebstyper eller sektorer denne måned?

VIGTIGT - Svar KUN med dette JSON format (ingen rå tekst):
{{"title": "...", "body": "..."}}

Tilføj en '## Diskussion' sektion EFTER tabellen med 2-3 spørgsmål:
- Er jeres organisation eller sektor berørt af lignende angreb?
- Har I set tegn på lignende aktivitet?
- Hvilke forholdsregler tager I mod denne type angreb?
(Tilpas spørgsmålene til månedens trends og hændelser)

Tilføj ALTID denne disclaimer NEDERST i body:

---
*Denne post er genereret af LLM med human oversight via mit open-source \
GitHub-projekt: https://github.com/LaZyDK/dkcyber-threat-monitor*
Rå data er verificeret af mig før posting.

Månedlig opsummering:
{raw_summary}"""

POST_PROMPT = """Du er en dansk cybersecurity-entusiast der poster i r/dkcybersecurity.
Skriv en engagerende Reddit-post på dansk om denne specifikke hændelse.

VIGTIGT - Svar KUN med dette JSON format (ingen anden tekst):
{{"title": "...", "body": "..."}}

Posten SKAL indeholde:
1. Dato: {timestamp}
2. Angrebstype: {attack_type}
3. Berørt sektor: {sector}
4. En GRUNDIG beskrivelse der kombinerer information fra ALLE kilder
5. ALLE kildelinks i markdown-format — dette er KRITISK, inkluder altid kildelinks
6. Hvis der er nøglefund fra flere kilder, fremhæv disse

Tilføj en '## Diskussion' sektion med 2-3 relevante spørgsmål til community.

Tilføj ALTID denne disclaimer NEDERST:

---
*Denne post er genereret af LLM med human oversight via mit open-source \
GitHub-projekt: https://github.com/LaZyDK/dkcyber-threat-monitor*
Rå data er verificeret af mig før posting.

Hændelse:
Titel: {name}
Beskrivelse: {description}
{enrichment_section}Kilder (SKAL inkluderes som links i posten):
{sources}"""


ENRICH_PROMPT = """Du er en dansk cybersikkerhedsanalytiker.
Du har fundet flere kilder om denne cyberhændelse:

Hændelse: {name}
Oprindelig beskrivelse: {description}

Yderligere kilder fundet:
{extra_sources}

Skriv en FORBEDRET beskrivelse på dansk (4-6 sætninger) der kombinerer \
information fra ALLE kilder. Inkluder nye detaljer, tidslinjer, eller \
konsekvenser som de ekstra kilder bidrager med.

VIGTIGT - Svar KUN med denne JSON (ingen anden tekst):
{{"enriched_description": "...", "key_findings": ["...", "..."]}}"""


def enrich_threat_sources(threat, brave_key, brave_url):
    """Search Brave for additional articles about a specific threat."""
    if not brave_key:
        return []

    name = threat.get('name', '')
    if not name:
        return []

    # Build a targeted search query from the threat name
    query = f"{name} cyberangreb"

    # Collect URLs we already have to avoid duplicates
    known_urls = {threat.get('link', '')}
    for src in threat.get('additional_sources', []):
        known_urls.add(src.get('url', ''))

    try:
        resp = requests.get(
            brave_url,
            headers={"Accept": "application/json",
                     "Accept-Encoding": "gzip",
                     "X-Subscription-Token": brave_key},
            params={"q": query, "count": 10,
                    "search_lang": "da", "freshness": "pm"},
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("web", {}).get("results", [])

        extra_sources = []
        for r in results:
            url = r.get("url", "")
            if not url or url in known_urls:
                continue
            # Skip if same domain as primary source
            known_urls.add(url)
            extra_sources.append({
                "url": url,
                "title": r.get("title", ""),
                "snippet": r.get("description", ""),
            })

        print(f"  Enrichment: found {len(extra_sources)} additional sources")
        return extra_sources[:5]  # Cap at 5 extra sources

    except requests.RequestException as e:
        print(f"  Enrichment search failed: {e}")
        return []


def summarize_sources(threat, extra_sources, api_key, api_url, model):
    """Use LLM to synthesize findings from all sources into enriched context."""
    if not extra_sources:
        return None

    sources_text = ""
    for i, src in enumerate(extra_sources, 1):
        sources_text += (
            f"{i}. [{src['title']}]({src['url']})\n"
            f"   {src['snippet']}\n\n"
        )

    prompt = ENRICH_PROMPT.format(
        name=threat.get('name', ''),
        description=threat.get('description', ''),
        extra_sources=sources_text,
    )

    result = _call_llm(prompt, api_key, api_url, model, max_tokens=800)
    if not result:
        return None

    return {
        "enriched_description": result.get("enriched_description", ""),
        "key_findings": result.get("key_findings", []),
        "extra_sources": extra_sources,
    }


def load_verified():
    if not os.path.exists(VERIFIED_PATH):
        return []
    with open(VERIFIED_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_verified(data):
    with open(VERIFIED_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_latest_file(pattern):
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        return None
    return files[0]


def get_reddit():
    required = ['REDDIT_CLIENT_ID', 'REDDIT_CLIENT_SECRET',
                'REDDIT_USERNAME', 'REDDIT_PASSWORD']
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"Reddit auth not configured (missing: {', '.join(missing)})"
              " — skipping Reddit post")
        return None
    return praw.Reddit(
        client_id=os.environ['REDDIT_CLIENT_ID'],
        client_secret=os.environ['REDDIT_CLIENT_SECRET'],
        username=os.environ['REDDIT_USERNAME'],
        password=os.environ['REDDIT_PASSWORD'],
        user_agent=(
            f"dkcyber-threat-bot/0.1 "
            f"(by u/{os.environ['REDDIT_USERNAME']})"
        ),
    )


def submit_to_reddit(reddit, title, body):
    subreddit = reddit.subreddit('dkcybersecurity')
    submission = subreddit.submit(title, selftext=body)
    reddit_url = submission.shortlink
    print(f"  Posted: {reddit_url}")
    return reddit_url


def generate_post_for_threat(threat, api_key, api_url, model,
                             brave_key="", brave_url=""):
    """Use LLM to generate a Reddit post for a single threat.

    If brave_key is provided, searches for additional sources first
    and summarizes findings for a richer post.
    """
    # Step 1: Enrich with additional sources via Brave Search
    enrichment = None
    if brave_key:
        extra_sources = enrich_threat_sources(threat, brave_key, brave_url)
        if extra_sources:
            enrichment = summarize_sources(
                threat, extra_sources, api_key, api_url, model)

    # Step 2: Build sources list (original + enrichment)
    sources_text = f"- [{threat.get('source', '')}]({threat.get('link', '')})"
    for src in threat.get('additional_sources', []):
        sources_text += f"\n- [{src.get('name', '')}]({src.get('url', '')})"

    enrichment_section = ""
    if enrichment:
        enrichment_section = (
            f"Forbedret beskrivelse baseret på flere kilder:\n"
            f"{enrichment['enriched_description']}\n\n"
        )
        if enrichment.get('key_findings'):
            enrichment_section += "Nøglefund fra yderligere kilder:\n"
            for finding in enrichment['key_findings']:
                enrichment_section += f"- {finding}\n"
            enrichment_section += "\n"

        # Add extra source links
        for src in enrichment.get('extra_sources', []):
            sources_text += (
                f"\n- [{src.get('title', 'Kilde')}]({src.get('url', '')})"
            )

    prompt = POST_PROMPT.format(
        timestamp=threat.get('timestamp', ''),
        attack_type=threat.get('attack_type', 'ukendt'),
        sector=threat.get('sector', 'ukendt'),
        name=threat.get('name', ''),
        description=threat.get('description', ''),
        enrichment_section=enrichment_section,
        sources=sources_text,
    )

    result = _call_llm(prompt, api_key, api_url, model)
    if not result:
        return None, None

    title = result.get('title', '').strip()
    body = result.get('body', '').strip()

    if not title or not body:
        print(f"  LLM returned empty title/body for {threat.get('name')}")
        return None, None
    return title, body


def validate_sources_in_body(body, threat):
    """Ensure the primary source link appears in the post body."""
    link = threat.get('link', '')
    if link and link not in body:
        # Append sources section if LLM forgot them
        sources_md = (
            f"\n\n## Kilder\n"
            f"- [{threat.get('source', 'Kilde')}]({link})"
        )
        for src in threat.get('additional_sources', []):
            sources_md += f"\n- [{src.get('name', 'Kilde')}]({src.get('url', '')})"
        body += sources_md
        print("  Added missing source links to post body")
    return body


def _call_llm(prompt, api_key, api_url, model, max_tokens=1400):
    """Call LLM and parse JSON response with escape fallback."""
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
                "temperature": 0.75,
                "max_tokens": max_tokens,
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        result = extract_json(content)
        if result is None:
            print(f"  LLM returned unparseable content: {content[:200]}")
        return result

    except (requests.RequestException, KeyError, IndexError) as e:
        print(f"  LLM call failed: {e}")
        return None


def _ensure_label(name, description, color):
    """Ensure a GitHub label exists (create if missing)."""
    subprocess.run(
        ["gh", "label", "create", name,
         "--description", description,
         "--color", color],
        capture_output=True, text=True,
    )


def _create_issue(title, body, labels):
    """Create a GitHub issue and return its URL."""
    for label in labels:
        _ensure_label(label, "", "FBCA04")

    result = subprocess.run(
        ["gh", "issue", "create",
         "--title", title,
         "--body", body,
         "--label", ",".join(labels)],
        capture_output=True, text=True,
    )

    if result.returncode == 0:
        issue_url = result.stdout.strip()
        print(f"  Created issue: {issue_url}")
        return issue_url
    else:
        print(f"  Failed to create issue: {result.stderr}")
        return None


def generate_issues():
    """Generate Reddit post text per threat and create GitHub Issues."""
    if not os.path.exists(NEWLY_ADDED_PATH):
        print("No newly_added.json found — nothing to generate")
        return

    with open(NEWLY_ADDED_PATH, 'r', encoding='utf-8') as f:
        newly_added_ids = json.load(f)

    if not newly_added_ids:
        print("No new threat IDs — nothing to generate")
        return

    verified = load_verified()
    threats_by_id = {e.get('id'): e for e in verified}

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    api_url = (os.environ.get("LLM_API_URL")
               or "https://openrouter.ai/api/v1/chat/completions")
    model = os.environ.get("LLM_MODEL_TOOLUSE", "")
    brave_key = os.environ.get("BRAVE_API_KEY", "")
    brave_url = (os.environ.get("BRAVE_SEARCH_URL")
                 or "https://api.search.brave.com/res/v1/web/search")

    if not api_key or not model:
        print("OPENROUTER_API_KEY or LLM_MODEL_TOOLUSE not set — cannot "
              "generate posts")
        return

    if not brave_key:
        print("BRAVE_API_KEY not set — posts will use existing sources only")

    created = 0
    failed_ids = []
    for threat_id in newly_added_ids:
        threat = threats_by_id.get(threat_id)
        if not threat:
            print(f"  Threat {threat_id} not found in verified — skipping")
            continue

        if threat.get('reddit_url'):
            print(f"  Threat {threat_id} already posted — skipping")
            continue

        print(f"Generating post for: {threat.get('name', threat_id)}")
        title, body = generate_post_for_threat(
            threat, api_key, api_url, model,
            brave_key=brave_key, brave_url=brave_url)

        if not title or not body:
            print(f"  Skipping {threat_id} — failed to generate post")
            failed_ids.append(threat_id)
            continue

        body = validate_sources_in_body(body, threat)

        # Create GitHub Issue with the post content for human review
        issue_title = f"Reddit post: {title}"
        issue_body = (
            f"## Reddit Post Preview\n\n"
            f"**Threat ID:** `{threat_id}`\n"
            f"**Attack type:** {threat.get('attack_type', 'ukendt')}\n"
            f"**Sector:** {threat.get('sector', 'ukendt')}\n\n"
            f"---\n\n"
            f"### Title\n{title}\n\n"
            f"### Body\n{body}\n\n"
            f"---\n\n"
            f"**Close this issue** to post to r/dkcybersecurity.\n"
            f"**Close as not planned** to reject (removes from "
            f"verified threats).\n"
            f"**Close as duplicate** to skip (removes from "
            f"verified threats)."
        )

        if _create_issue(issue_title, issue_body,
                         ["reddit-post-pending"]):
            created += 1
        else:
            failed_ids.append(threat_id)

    # Write back failed IDs so they can be retried next run
    if failed_ids:
        with open(NEWLY_ADDED_PATH, 'w', encoding='utf-8') as f:
            json.dump(failed_ids, f, ensure_ascii=False, indent=2)
        print(f"  {len(failed_ids)} threats failed — kept in "
              "newly_added.json for retry")
    else:
        # All succeeded — clean up
        if os.path.exists(NEWLY_ADDED_PATH):
            os.remove(NEWLY_ADDED_PATH)

    print(f"Created {created} review issues")


def _extract_threat_id(issue_body):
    """Extract threat ID from issue body."""
    id_match = re.search(r'\*\*Threat ID:\*\* `(.+?)`', issue_body)
    return id_match.group(1) if id_match else None


def _extract_month(issue_body):
    """Extract month from monthly summary issue body."""
    month_match = re.search(r'\*\*Month:\*\* (\d{4}-\d{2})', issue_body)
    return month_match.group(1) if month_match else None


def _is_monthly_issue(issue_body):
    """Check if this is a monthly summary issue."""
    return '**Type:** monthly-summary' in issue_body


def _read_issue(issue_number):
    """Read issue data via gh CLI."""
    result = subprocess.run(
        ["gh", "issue", "view", str(issue_number),
         "--json", "body,title,stateReason"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Failed to read issue #{issue_number}: {result.stderr}")
        sys.exit(1)
    return json.loads(result.stdout)


def handle_issue(issue_number, state_reason):
    """Handle a closed issue based on its close reason."""
    issue_data = _read_issue(issue_number)
    issue_body = issue_data['body']
    is_monthly = _is_monthly_issue(issue_body)
    threat_id = _extract_threat_id(issue_body)

    # Use state_reason from workflow event (more reliable than API)
    reason = state_reason or issue_data.get('stateReason', 'completed')

    if reason == 'not_planned':
        if is_monthly:
            print("Monthly summary rejected — no action needed")
        elif threat_id:
            verified = load_verified()
            before = len(verified)
            verified = [e for e in verified if e.get('id') != threat_id]
            after = len(verified)
            if after < before:
                save_verified(verified)
                print(f"Removed threat {threat_id} from "
                      "verified_threats.json (closed as not planned)")
            else:
                print(f"Threat {threat_id} not found in verified — "
                      "nothing to remove")
        else:
            print("No threat ID found in issue — nothing to remove")
        return

    # state_reason == 'completed' → post to Reddit
    title_match = re.search(r'### Title\n(.+?)(?:\n\n|\n###)', issue_body,
                            re.DOTALL)
    body_match = re.search(r'### Body\n(.+?)(?:\n\n---|\Z)', issue_body,
                           re.DOTALL)

    if not title_match or not body_match:
        print("Could not parse title/body from issue — check format")
        sys.exit(1)

    post_title = title_match.group(1).strip()
    post_body = body_match.group(1).strip()

    reddit = get_reddit()
    if not reddit:
        print("Skipping Reddit post (auth not configured)")
        return

    reddit_url = submit_to_reddit(reddit, post_title, post_body)

    if is_monthly:
        # Tag all untagged threats with the monthly summary URL
        month = _extract_month(issue_body)
        verified = load_verified()
        updated = 0
        for entry in verified:
            if not entry.get('reddit_url'):
                entry['reddit_url'] = reddit_url
                updated += 1
        if updated:
            save_verified(verified)
            print(f"Tagged {updated} threats with monthly URL "
                  f"({month}): {reddit_url}")
    elif threat_id:
        verified = load_verified()
        for entry in verified:
            if entry.get('id') == threat_id:
                entry['reddit_url'] = reddit_url
                break
        save_verified(verified)
        print(f"Tagged threat {threat_id} with {reddit_url}")

    subprocess.run(
        ["gh", "issue", "comment", str(issue_number),
         "--body", f"Posted to Reddit: {reddit_url}"],
    )


def generate_monthly_issue():
    """Generate monthly summary post via LLM and create GitHub Issue."""
    raw_file = find_latest_file('data/monthly/summary_*.json')
    if not raw_file:
        print("No monthly raw summary found — nothing to generate")
        return

    with open(raw_file, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    month = raw_data.get('month', 'unknown')
    raw_summary = raw_data.get('table_markdown', '')
    if not raw_summary:
        print("Monthly summary is empty — nothing to generate")
        return

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    api_url = (os.environ.get("LLM_API_URL")
               or "https://openrouter.ai/api/v1/chat/completions")
    model = os.environ.get("LLM_MODEL_TOOLUSE", "")

    if not api_key or not model:
        print("OPENROUTER_API_KEY or LLM_MODEL_TOOLUSE not set — cannot "
              "generate monthly post")
        return

    print(f"Generating monthly summary for {month}...")
    prompt = MONTHLY_PROMPT.format(raw_summary=raw_summary)
    result = _call_llm(prompt, api_key, api_url, model, max_tokens=1800)

    if not result:
        print("Failed to generate monthly post")
        return

    title = result.get('title', '').strip()
    body = result.get('body', '').strip()

    if not title or not body:
        print("LLM returned empty title/body for monthly post")
        return

    issue_title = f"Månedlig opsummering: {title}"
    issue_body = (
        f"## Monthly Summary Preview\n\n"
        f"**Type:** monthly-summary\n"
        f"**Month:** {month}\n\n"
        f"---\n\n"
        f"### Title\n{title}\n\n"
        f"### Body\n{body}\n\n"
        f"---\n\n"
        f"**Close this issue** to post to r/dkcybersecurity.\n"
        f"**Close as not planned** to skip posting."
    )

    _create_issue(issue_title, issue_body, ["reddit-post-pending"])


def main():
    if len(sys.argv) < 2:
        print("Usage: post_to_reddit.py <mode> [args]")
        print("Modes: generate, generate-monthly, handle-closed")
        sys.exit(1)

    mode = sys.argv[1]

    if mode == 'generate':
        generate_issues()
    elif mode == 'generate-monthly':
        generate_monthly_issue()
    elif mode == 'handle-closed':
        if len(sys.argv) < 3:
            print("Usage: post_to_reddit.py handle-closed <issue_number>"
                  " [state_reason]")
            sys.exit(1)
        issue_num = sys.argv[2]
        reason = sys.argv[3] if len(sys.argv) > 3 else None
        handle_issue(issue_num, reason)
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)


if __name__ == '__main__':
    main()
