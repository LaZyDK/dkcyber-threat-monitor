import praw
import json
import os
import sys
import glob


VERIFIED_PATH = 'data/verified_threats.json'


def find_latest_file(pattern):
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        return None
    return files[0]


def load_post(post_file):
    """Load title and body from a JSON post file."""
    with open(post_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['title'].strip(), data['body']


def post_to_reddit(title, body):
    reddit = praw.Reddit(
        client_id=os.environ['REDDIT_CLIENT_ID'],
        client_secret=os.environ['REDDIT_CLIENT_SECRET'],
        username=os.environ['REDDIT_USERNAME'],
        password=os.environ['REDDIT_PASSWORD'],
        user_agent=(
            f"dkcyber-threat-bot/0.1 "
            f"(by u/{os.environ['REDDIT_USERNAME']})"
        ),
    )

    subreddit = reddit.subreddit('dkcybersecurity')
    submission = subreddit.submit(title, selftext=body)

    reddit_url = submission.shortlink
    print(f"Posted: {reddit_url}")
    return reddit_url


def save_reddit_url(reddit_url):
    if not os.path.exists(VERIFIED_PATH):
        return

    with open(VERIFIED_PATH, 'r', encoding='utf-8') as f:
        verified = json.load(f)

    if not verified:
        return

    # Tag all entries that don't yet have a reddit_url
    # with the monthly summary post link
    updated = 0
    for entry in verified:
        if not entry.get('reddit_url'):
            entry['reddit_url'] = reddit_url
            updated += 1

    with open(VERIFIED_PATH, 'w', encoding='utf-8') as f:
        json.dump(verified, f, ensure_ascii=False, indent=2)

    print(f"Updated {updated} entries with reddit_url: {reddit_url}")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'monthly'

    if mode == 'monthly':
        post_file = find_latest_file('data/monthly/generated/post_*.json')
    else:
        post_file = find_latest_file('data/daily/generated/post_*.json')

    if not post_file:
        print(f"No {mode} post file found — skipping")
        sys.exit(1)

    title, body = load_post(post_file)
    reddit_url = post_to_reddit(title, body)
    save_reddit_url(reddit_url)


if __name__ == '__main__':
    main()
