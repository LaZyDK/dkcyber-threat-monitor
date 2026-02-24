# dkcybersecurity Threat Monitor 🤖

[![AI Transparency](https://img.shields.io/badge/🤖%20AI%20Transparency-LLM%20Generated%20with%20Human%20Oversight-00bfff?style=for-the-badge&logo=artificial-intelligence&logoColor=white)](https://github.com/LaZyDK/dkcyber-threat-monitor#ai-transparency)

**Automatisk overvågning og deling af verificerede cyber-trusler til det danske community.**

Dette open-source projekt indsamler trusler fra offentlige kilder (RSS-feeds + offentlige Telegram-kanaler fra kendte APT-grupper), lader **mig** verificere dem via Pull Requests, og poster derefter automatisk til **r/dkcybersecurity**.

### Hvordan det virker

1. **Rå data** → indsamles automatisk  
2. **Draft (billig model)** → hurtigt udkast (`LLM_MODEL_CHEAP`, fx openai/gpt-3.5-turbo)  
3. **Finalize (tool-use model)** → færdig Reddit-post (`LLM_MODEL_TOOLUSE`, fx anthropic/claude-3-opus)  
4. **Human oversight** → jeg gennemgår og godkender alt i PR  
5. **Månedlig opsummering** → samme decoupled proces den 1. i hver måned

#### LLM Model Environment Variables

- `LLM_MODEL_CHEAP`: Bruges til hurtige, billige udkast (ingen tool use)
- `LLM_MODEL_TOOLUSE`: Bruges til trin der kræver tool use eller bedre kvalitet

Disse sættes som repo secrets eller i workflow env.

### AI Transparency

**Alle tekster i dette projekt er genereret af LLM’er med human oversight.**

- Rå data er 100 % fra kilden og gemmes uændret (`data/raw/` og `data/verified_threats.json`).
- LLM-teksten er kun et udkast – jeg læser, retter og godkender **altid** før posting.
- Du kan følge hele processen i repo’ets Pull Requests og commit-historik.

**Hver Reddit-post indeholder desuden denne faste disclaimer** (automatisk tilføjet af Finalize-step):
> ---
> 🤖 *Denne post er genereret af LLM (Llama 3.1 70B) med human oversight via et open-source GitHub-projekt: https://github.com/LaZyDK/dkcyber-threat-monitor*
> Rå data er verificeret af mig før posting.

### Teknisk opsætning

- 100 % GitHub Actions (undtagen Telegram-scraper på VPS)
- Decoupled multi-step workflows (ingen kæder, ingen agent1/agent2-navne)
- Gratis og betalte LLMs (vælg model via env vars)
- Alt versioneret: raw → draft → final post

#### Opsætning af secrets

- `OPENROUTER_API_KEY` (OpenRouter LLM adgang)
- `BRAVE_API_KEY` (Brave Search API)
- `LLM_MODEL_CHEAP` (fx openai/gpt-3.5-turbo)
- `LLM_MODEL_TOOLUSE` (fx anthropic/claude-3-opus)
- (Valgfrit) Reddit API credentials til auto-posting

### Links

- Reddit: [r/dkcybersecurity](https://www.reddit.com/r/dkcybersecurity/)
- Issues & forslag: [Åbn et issue](../../issues)

**Made with ❤️ af en dansk cybersecurity-entusiast – og en flok venlige open-source LLMs.**

---

**Licens:** MIT  
**Sidst opdateret:** februar 2026