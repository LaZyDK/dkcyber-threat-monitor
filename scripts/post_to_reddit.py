import praw
import json
import os
import re
import subprocess
import sys
import glob
import requests


VERIFIED_PATH = 'data/verified_threats.json'
NEWLY_ADDED_PATH = 'data/daily/newly_added.json'

POST_PROMPT = """Du er en dansk cybersecurity-entusiast der poster i r/dkcybersecurity.
Skriv en engagerende Reddit-post på dansk om denne specifikke hændelse.

VIGTIGT - Svar KUN med dette JSON format (ingen anden tekst):
{{"title": "...", "body": "..."}}

Posten SKAL indeholde:
1. Dato: {timestamp}
2. Angrebstype: {attack_type}
3. Berørt sektor: {sector}
4. Beskrivelse af hændelsen
5. ALLE kildelinks i markdown-format — dette er KRITISK, inkluder altid kildelinks

Tilføj en '## Diskussion' sektion med 2-3 relevante spørgsmål til community.

Tilføj ALTID denne disclaimer NEDERST:

---
*Denne post er genereret af LLM med human oversight via mit open-source \
GitHub-projekt: https://github.com/LaZyDK/dkcyber-threat-monitor*
Rå data er verificeret af mig før posting.

Hændelse:
Titel: {name}
Beskrivelse: {description}
Kilder (SKAL inkluderes som links i posten):
{sources}"""


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


def generate_post_for_threat(threat, api_key, api_url, model):
    """Use LLM to generate a Reddit post for a single threat."""
    sources_text = f"- [{threat.get('source', '')}]({threat.get('link', '')})"
    for src in threat.get('additional_sources', []):
        sources_text += f"\n- [{src.get('name', '')}]({src.get('url', '')})"

    prompt = POST_PROMPT.format(
        timestamp=threat.get('timestamp', ''),
        attack_type=threat.get('attack_type', 'ukendt'),
        sector=threat.get('sector', 'ukendt'),
        name=threat.get('name', ''),
        description=threat.get('description', ''),
        sources=sources_text,
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
                "temperature": 0.75,
                "max_tokens": 1400,
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
        title = result.get('title', '').strip()
        body = result.get('body', '').strip()

        if not title or not body:
            print(f"  LLM returned empty title/body for {threat.get('name')}")
            return None, None
        return title, body

    except (requests.RequestException, json.JSONDecodeError,
            KeyError, IndexError) as e:
        print(f"  LLM post generation failed: {e}")
        return None, None


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

    if not api_key or not model:
        print("OPENROUTER_API_KEY or LLM_MODEL_TOOLUSE not set — cannot "
              "generate posts")
        return

    created = 0
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
            threat, api_key, api_url, model)

        if not title or not body:
            print(f"  Skipping {threat_id} — failed to generate post")
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
            f"Add the `approved` label to post this to r/dkcybersecurity."
        )

        result = subprocess.run(
            ["gh", "issue", "create",
             "--title", issue_title,
             "--body", issue_body,
             "--label", "reddit-post-pending"],
            capture_output=True, text=True,
        )

        if result.returncode == 0:
            issue_url = result.stdout.strip()
            print(f"  Created issue: {issue_url}")
            created += 1
        else:
            print(f"  Failed to create issue: {result.stderr}")

    print(f"Created {created} review issues")


def post_approved(issue_number):
    """Post an approved issue's content to Reddit."""
    # Read issue body via gh CLI
    result = subprocess.run(
        ["gh", "issue", "view", str(issue_number),
         "--json", "body,title"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Failed to read issue #{issue_number}: {result.stderr}")
        sys.exit(1)

    issue_data = json.loads(result.stdout)
    issue_body = issue_data['body']

    # Parse the title and body from the issue markdown
    title_match = re.search(r'### Title\n(.+?)(?:\n\n|\n###)', issue_body,
                            re.DOTALL)
    body_match = re.search(r'### Body\n(.+?)(?:\n\n---|\Z)', issue_body,
                           re.DOTALL)

    if not title_match or not body_match:
        print("Could not parse title/body from issue — check format")
        sys.exit(1)

    post_title = title_match.group(1).strip()
    post_body = body_match.group(1).strip()

    # Extract threat ID
    id_match = re.search(r'\*\*Threat ID:\*\* `(.+?)`', issue_body)
    threat_id = id_match.group(1) if id_match else None

    # Post to Reddit
    reddit = get_reddit()
    reddit_url = submit_to_reddit(reddit, post_title, post_body)

    # Update verified_threats.json with the reddit_url
    if threat_id:
        verified = load_verified()
        for entry in verified:
            if entry.get('id') == threat_id:
                entry['reddit_url'] = reddit_url
                break
        save_verified(verified)
        print(f"Tagged threat {threat_id} with {reddit_url}")

    # Close the issue
    subprocess.run(
        ["gh", "issue", "close", str(issue_number),
         "--comment", f"Posted to Reddit: {reddit_url}"],
    )


def monthly_post():
    """Post monthly summary (single combined post)."""
    post_file = find_latest_file('data/monthly/generated/post_*.json')
    if not post_file:
        print("No monthly post file found — skipping")
        sys.exit(1)

    with open(post_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    title = data['title'].strip()
    body = data['body']

    reddit = get_reddit()
    reddit_url = submit_to_reddit(reddit, title, body)

    # Tag untagged threats with the monthly summary URL
    verified = load_verified()
    updated = 0
    for entry in verified:
        if not entry.get('reddit_url'):
            entry['reddit_url'] = reddit_url
            updated += 1

    if updated:
        save_verified(verified)
        print(f"Updated {updated} entries with monthly reddit_url")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'monthly'

    if mode == 'generate':
        generate_issues()
    elif mode == 'post-approved':
        if len(sys.argv) < 3:
            print("Usage: post_to_reddit.py post-approved <issue_number>")
            sys.exit(1)
        post_approved(sys.argv[2])
    elif mode == 'monthly':
        monthly_post()
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)


if __name__ == '__main__':
    main()
