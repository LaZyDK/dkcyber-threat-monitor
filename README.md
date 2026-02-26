# dkcybersecurity Threat Monitor

[![AI Transparency](https://img.shields.io/badge/AI%20Transparency-LLM%20Generated%20with%20Human%20Oversight-00bfff?style=for-the-badge)](https://github.com/LaZyDK/dkcyber-threat-monitor#ai-transparency)

**Automatisk overvagning og deling af verificerede cyber-trusler til det danske community.**

Dette open-source projekt indsamler trusler fra offentlige kilder (RSS-feeds og Brave Search), lader **mig** verificere dem via Pull Requests, og poster derefter automatisk til **r/dkcybersecurity**.

## Hvordan det virker

### Track A — Enkelte trusler

1. **Indsamling** (workflow 01, hver 3. time) — RSS-feeds fra `data/feeds.json` + keyword pre-filter + LLM-klassificering
2. **Verifikation** — PR oprettes med klassificerede trusler. Hver kørsel = et commit, så du reviewer kun nye data
3. **Merge** (workflow 02) — Verificerede trusler tilføjes `data/verified_threats.json`. LLM merger artikler om samme angreb
4. **Draft** (workflow 02-daily) — Hurtigt udkast via `LLM_MODEL_CHEAP` (kun baseret på verificerede DK-angreb)
5. **Finalize** (workflow 03) — Færdig Reddit-post via `LLM_MODEL_TOOLUSE` med transparency disclaimer

### Track B — Manedlig opsummering

1. **Opsummering** (workflow 04) — Genererer tabel over forrige maneds trusler
2. **Draft + Finalize** (workflow 05-06) — Samme decoupled LLM-proces
3. **Post til Reddit** (workflow 08) — Poster til r/dkcybersecurity og gemmer reddit_url

### Aktiv opdagelse

- **Brave Search** (workflow 09) — Soger dagligt efter danske cyberangreb fra kilder uden for RSS-feeds
- **Ny-kilde-opdagelse** (workflow 10) — Prober opdagede domaner for RSS-feeds og opretter PR til `data/feeds.json`

## Data model

Hver verificeret trussel i `data/verified_threats.json`:

```json
{
  "id": "a4c7c0352b20",
  "name": "Russiske DDoS-angreb pa 40 danske hjemmesider",
  "description": "Russiske hackergrupper har udfort DDoS-angreb...",
  "source": "tjekdet.dk",
  "link": "https://www.tjekdet.dk/...",
  "additional_sources": [
    {"url": "https://finans.dk/...", "name": "finans.dk"},
    {"url": "https://bt.dk/...", "name": "bt.dk"}
  ],
  "timestamp": "2026-02-24",
  "verified_by": "human-review",
  "verified_at": "2026-02-24T12:07:24+00:00"
}
```

Flere artikler om **samme angreb** merges automatisk. Primary link + source bevares, yderligere kilder gemmes i `additional_sources`.

## Deduplikering og merging

- **URL-deduplikering** — Samme URL kan aldrig optræde i flere PRs. Checker mod `verified_threats.json` og alle `data/raw/*.json` filer
- **URL-cleaning** — Tracking-parametre (utm_*, gaa_*, fbclid, etc.) strippes automatisk ved indsamling, så samme artikel med forskellige tracking-links ikke duplikeres
- **Attack merging** — Når PRs merges, bruger LLM'en til at gruppere artikler der handler om samme hændelse. 16 artikler om russiske DDoS-angreb blev fx merget til 2 distinkte events

## RSS-kilder

Kilder styres centralt i [`data/feeds.json`](data/feeds.json). Alle scripts laeser herfra.

Nye kilder opdages automatisk via Brave Search og forelaas via PR. Du kan ogsa tilfojes manuelt:

```json
{
  "url": "https://www.cert.dk/news/rss",
  "name": "DKCERT",
  "language": "da",
  "added": "2026-02-01",
  "added_by": "manual"
}
```

## Opsaetning

### Secrets (repo → Settings → Secrets → Actions)

| Secret | Brug |
|--------|------|
| `OPENROUTER_API_KEY` | LLM-adgang via OpenRouter |
| `BRAVE_API_KEY` | Brave Search API (gratis: 2000 queries/md) |
| `REDDIT_CLIENT_ID` | Reddit API (valgfrit) |
| `REDDIT_CLIENT_SECRET` | Reddit API (valgfrit) |
| `REDDIT_USERNAME` | Reddit API (valgfrit) |
| `REDDIT_PASSWORD` | Reddit API (valgfrit) |

### Variables (repo → Settings → Variables → Actions)

| Variable | Brug | Default |
|----------|------|---------|
| `LLM_MODEL_CHEAP` | Klassificering, merging og udkast (fx `qwen/qwen3-vl-30b-a3b-thinking`) | (paakraevet) |
| `LLM_MODEL_TOOLUSE` | Finalize-trin med tool use (fx `openai/gpt-3.5-turbo`) | (paakraevet) |
| `LLM_API_URL` | LLM API endpoint | `https://openrouter.ai/api/v1/chat/completions` |
| `BRAVE_SEARCH_URL` | Brave Search endpoint | `https://api.search.brave.com/res/v1/web/search` |

### Workflow permissions

Repo → Settings → Actions → General → Workflow permissions:
- **"Read and write permissions"**
- **"Allow GitHub Actions to create and approve pull requests"**

## Klassificering

LLM-klassificeringen bruger strenge regler for at undgå false positives:

- Artiklen SKAL nævne et **konkret dansk offer eller mål** for at tælle som dansk angreb
- Danske kilder (DK CERT, Version2 etc.) der rapporterer om internationale hændelser tæller IKKE
- Generelle CVE-advarsler, tips og guides filtreres fra
- Angreb med ukendt type nedgraderes automatisk

## AI Transparency

**Alle tekster i dette projekt er genereret af LLM'er med human oversight.**

- Rå data er 100 % fra kilden og gemmes uændret (`data/raw/` og `data/verified_threats.json`)
- LLM-teksten er kun et udkast — jeg læser, retter og godkender **altid** før posting
- Du kan følge hele processen i repo'ets Pull Requests og commit-historik

**Hver Reddit-post indeholder denne faste disclaimer** (automatisk tilføjet):
> ---
> *Denne post er genereret af LLM med human oversight via mit open-source GitHub-projekt: https://github.com/LaZyDK/dkcyber-threat-monitor*
> Rå data er verificeret af mig før posting.

## Workflows

| # | Navn | Trigger | Beskrivelse |
|---|------|---------|-------------|
| 01 | Collect Raw Threats | Hver 3. time + manual | RSS-feeds → keyword filter → LLM-klassificering → PR (et commit per kørsel) |
| 02 | Merge to Verified | PR merge med `data/raw/**` | Append + LLM-merge → `verified_threats.json` + oprydning |
| 02-daily | Daily Draft | Push til `data/raw/**` | LLM-udkast kun baseret på verificerede DK-angreb |
| 03 | Daily Finalize | Efter draft | Færdig Reddit-post med disclaimer |
| 04 | Monthly Raw Summary | 1. i hver måned | Tabel over forrige måneds trusler |
| 05 | Monthly Draft | Efter monthly summary | Månedligt LLM-udkast |
| 06 | Monthly Finalize | Efter monthly draft | Færdig månedlig post |
| 08 | Monthly Post to Reddit | Efter monthly finalize | Poster til r/dkcybersecurity |
| 09 | Discover Threats | Dagligt kl. 10 UTC + manual | Brave Search → LLM → PR (et commit per kørsel) |
| 10 | Suggest Sources | Når nye kandidater opdages | Prober RSS-feeds → PR til `feeds.json` (kun virkelig nye kilder) |

## Links

- Reddit: [r/dkcybersecurity](https://www.reddit.com/r/dkcybersecurity/)
- Issues & forslag: [Abn et issue](../../issues)

---

**Licens:** MIT
