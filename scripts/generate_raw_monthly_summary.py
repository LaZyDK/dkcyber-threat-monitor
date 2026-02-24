import pandas as pd
import json
import os
from datetime import datetime, timedelta

VERIFIED_PATH = 'data/verified_threats.json'


def generate_raw_monthly_summary():
    if not os.path.exists(VERIFIED_PATH):
        print(f"Verified file {VERIFIED_PATH} does not exist yet → skipping")
        return

    try:
        with open(VERIFIED_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError:
        print("Verified file is invalid JSON → skipping")
        return

    if not data:
        print("No verified threats yet → nothing to summarize")
        return

    df = pd.DataFrame(data)

    # Assume each entry has at least 'date' in ISO format 'YYYY-MM-DD...'
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date'])

    now = datetime.now()
    first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    first_of_last_month = (first_of_this_month - timedelta(days=1)).replace(day=1)

    last_month_str = first_of_last_month.strftime('%Y-%m')

    monthly = df[df['date'].dt.strftime('%Y-%m') == last_month_str]

    if monthly.empty:
        print(f"No verified threats in {last_month_str} → skipping")
        return

    # Customize columns to whatever fields you actually store
    columns = ['title', 'date', 'source', 'link', 'reddit_url', 'short_desc']
    existing_cols = [c for c in columns if c in monthly.columns]
    table_md = monthly[existing_cols].to_markdown(index=False)

    summary = {
        "month": last_month_str,
        "count": len(monthly),
        "table_markdown": table_md,
        "generated_at": now.isoformat()
    }

    os.makedirs('data/monthly/raw', exist_ok=True)
    out_path = f'data/monthly/raw/summary_{last_month_str}.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"Monthly raw summary created: {out_path} ({summary['count']} threats)")


if __name__ == '__main__':
    generate_raw_monthly_summary()
