# dkcybersecurity Threat Monitor

[![AI Transparency](https://img.shields.io/badge/AI%20Transparency-LLM%20Generated%20with%20Human%20Oversight-00bfff?style=for-the-badge)](https://github.com/LaZyDK/dkcyber-threat-monitor#ai-transparency)

**Automatisk overvågning og deling af verificerede cyber-trusler til det danske community.**

Dette open-source projekt indsamler trusler fra offentlige kilder (RSS-feeds og Brave Search), lader **mig** verificere dem via Pull Requests, og poster derefter automatisk til **r/dkcybersecurity** — efter endnu en menneskelig godkendelse via GitHub Issues.

## Hvordan det virker

### Track A — Enkelte trusler

1. **Indsamling** (workflow 01, hver 3. time) — RSS-feeds fra `data/feeds.json` + keyword pre-filter + LLM-klassificering
2. **Verifikation** — PR oprettes med klassificerede trusler. Hver kørsel = et commit, så du reviewer kun nye data
3. **Merge + Issue** (workflow 02) — Ved PR-merge: verificerede trusler tilføjes `data/verified_threats.json`, LLM merger artikler om samme angreb, og der oprettes et **GitHub Issue per trussel** med genereret Reddit-post til review
4. **Godkendelse** (workflow 03) — Luk issue'et → posten sendes automatisk til r/dkcybersecurity

### Track B — Månedlig opsummering

1. **Opsummering + Issue** (workflow 04, 1. i hver måned) — Genererer tabel over forrige måneds trusler → LLM skriver Reddit-post → GitHub Issue oprettes til review
2. **Godkendelse** (workflow 03) — Luk issue'et → posten sendes automatisk til r/dkcybersecurity (samme flow som Track A)

### Aktiv opdagelse

- **Brave Search** (workflow 05) — Søger dagligt efter danske cyberangreb fra kilder uden for RSS-feeds
- **Ny-kilde-opdagelse** (workflow 06) — Prober opdagede domæner for RSS-feeds og opretter PR til `data/feeds.json`

## Data model

Hver verificeret trussel i `data/verified_threats.json`:

```json
{
  "id": "a4c7c0352b20",
  "name": "Russiske DDoS-angreb på 40 danske hjemmesider",
  "description": "Russiske hackergrupper har udført DDoS-angreb...",
  "attack_type": "ddos",
  "sector": "offentlig",
  "source": "tjekdet.dk",
  "link": "https://www.tjekdet.dk/...",
  "additional_sources": [
    {"url": "https://finans.dk/...", "name": "finans.dk"},
    {"url": "https://bt.dk/...", "name": "bt.dk"}
  ],
  "timestamp": "2026-02-24",
  "verified_by": "human-review",
  "verified_at": "2026-02-24T12:07:24+00:00",
  "reddit_url": "https://redd.it/..."
}
```

Flere artikler om **samme angreb** merges automatisk. Primary link + source bevares, yderligere kilder gemmes i `additional_sources`.

## Deduplikering og merging

- **URL-deduplikering** — Samme URL kan aldrig optræde i flere PRs. Checker mod `verified_threats.json` og `data/analyzed_urls.json`
- **URL-cleaning** — Tracking-parametre (utm_*, gaa_*, fbclid, etc.) strippes automatisk ved indsamling, så samme artikel med forskellige tracking-links ikke duplikeres
- **Attack merging** — Når PRs merges, bruger LLM'en til at gruppere artikler der handler om samme hændelse

## Confidence-feltet

`confidence` angiver LLM'ens sikkerhed på at angrebet **faktisk rammer Danmark**:

| Værdi | Betydning |
|-------|-----------|
| `high` | Klart dansk mål nævnt |
| `medium` | Sandsynligt dansk |
| `low` | Usikkert/tvivlsomt |
| `keyword-only` | Keyword-match, ingen LLM-verifikation |
| `error` | LLM-klassificering fejlede |

## RSS-kilder

Kilder styres centralt i [`data/feeds.json`](data/feeds.json). Alle scripts læser herfra.

Nye kilder opdages automatisk via Brave Search og foreslås via PR. Du kan også tilføje manuelt:

```json
{
  "url": "https://www.cert.dk/news/rss",
  "name": "DKCERT",
  "language": "da",
  "added": "2026-02-01",
  "added_by": "manual"
}
```

## Opsætning

### Secrets (repo → Settings → Secrets → Actions)

| Secret | Brug |
|--------|------|
| `OPENROUTER_API_KEY` | LLM-adgang via OpenRouter |
| `BRAVE_API_KEY` | Brave Search API (gratis: 2000 queries/md) |
| `REDDIT_CLIENT_ID` | Reddit API |
| `REDDIT_CLIENT_SECRET` | Reddit API |
| `REDDIT_USERNAME` | Reddit API |
| `REDDIT_PASSWORD` | Reddit API |

### Variables (repo → Settings → Variables → Actions)

| Variable | Brug | Default |
|----------|------|---------|
| `LLM_MODEL_CHEAP` | Klassificering, merging (fx `qwen/qwen3-vl-30b-a3b-thinking`) | (påkrævet) |
| `LLM_MODEL_TOOLUSE` | Reddit-post generering (fx `openai/gpt-3.5-turbo`) | (påkrævet) |
| `LLM_API_URL` | LLM API endpoint | `https://openrouter.ai/api/v1/chat/completions` |
| `BRAVE_SEARCH_URL` | Brave Search endpoint | `https://api.search.brave.com/res/v1/web/search` |

### Workflow permissions

Repo → Settings → Actions → General → Workflow permissions:
- **"Read and write permissions"**
- **"Allow GitHub Actions to create and approve pull requests"**

### GitHub Labels

Workflow 03 trigges når et issue med `reddit-post-pending` label lukkes. Labelet oprettes automatisk ved første brug.

## Klassificering

LLM-klassificeringen bruger strenge regler for at undgå false positives:

- Artiklen SKAL nævne et **konkret dansk offer eller mål** for at tælle som dansk angreb
- Danske kilder (DK CERT, Version2 etc.) der rapporterer om internationale hændelser tæller IKKE
- Generelle CVE-advarsler, tips og guides filtreres fra
- Angreb med ukendt type nedgraderes automatisk

## AI Transparency

**Alle tekster i dette projekt er genereret af LLM'er med human oversight.**

- Rå data er 100 % fra kilden og gemmes uændret (`data/daily/` og `data/verified_threats.json`)
- LLM-teksten er kun et udkast — jeg læser, retter og godkender **altid** før posting via GitHub Issues
- Du kan følge hele processen i repo'ets Pull Requests, Issues og commit-historik

**Hver Reddit-post indeholder denne faste disclaimer** (automatisk tilføjet):
> ---
> *Denne post er genereret af LLM med human oversight via mit open-source GitHub-projekt: https://github.com/LaZyDK/dkcyber-threat-monitor*
> Rå data er verificeret af mig før posting.

## Workflows

| # | Navn | Trigger | Beskrivelse |
|---|------|---------|-------------|
| 01 | Collect Raw Threats | Hver 3. time + manual | RSS-feeds → keyword filter → LLM-klassificering → PR |
| 02 | Merge + Generate Posts | PR merge med `data/daily/**` | Append + LLM-merge → `verified_threats.json` + GitHub Issue per trussel |
| 03 | Post Approved | Issue lukkes med `reddit-post-pending` label | Poster til r/dkcybersecurity → tagger `reddit_url` |
| 04 | Monthly Summary | 1. i hver måned | Opsummering → LLM-post → GitHub Issue til review |
| 05 | Discover Threats | Dagligt kl. 10 UTC + manual | Brave Search → LLM → PR |
| 06 | Suggest Sources | Når nye kandidater opdages | Prober RSS-feeds → PR til `feeds.json` |

## Mappestruktur

```
data/
├── daily/                ← Rå indsamlede trusler (slettes efter merge)
├── monthly/              ← Månedlig opsummering (slettes efter issue-oprettelse)
├── feeds.json            ← RSS-kilder
├── danish_entities.json   ← Keyword-mønstre til pre-filter
├── analyzed_urls.json     ← Ledger over analyserede URLs
└── verified_threats.json  ← Verificerede trusler (hovedfil)
```

## Links

- Reddit: [r/dkcybersecurity](https://www.reddit.com/r/dkcybersecurity/)
- Issues & forslag: [Åbn et issue](../../issues)

---

**Licens:** MIT
