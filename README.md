# dkcybersecurity Threat Monitor 🤖

[![AI Transparency](https://img.shields.io/badge/🤖%20AI%20Transparency-LLM%20Generated%20with%20Human%20Oversight-00bfff?style=for-the-badge&logo=artificial-intelligence&logoColor=white)](https://github.com/LaZyDK/dkcyber-threat-monitor#ai-transparency)

**Automatisk overvågning og deling af verificerede cyber-trusler til det danske community.**

Dette open-source projekt indsamler trusler fra offentlige kilder (RSS-feeds + offentlige Telegram-kanaler fra kendte APT-grupper), lader **mig** verificere dem via Pull Requests, og poster derefter automatisk til **r/dkcybersecurity**.

### Hvordan det virker

1. **Rå data** → indsamles automatisk  
2. **Agent 1 (GitHub Models – gratis)** → laver hurtigt udkast  
3. **Agent 2 (Llama 3.1 70B via OpenRouter/Groq – gratis tier)** → laver færdig Reddit-post  
4. **Human oversight** → jeg gennemgår og godkender alt i PR  
5. **Månedlig opsummering** → samme decoupled proces den 1. i hver måned

### AI Transparency

**Alle tekster i dette projekt er genereret af LLM’er med human oversight.**

- Rå data er 100 % fra kilden og gemmes uændret (`data/raw/` og `data/verified_threats.json`).
- LLM-teksten er kun et udkast – jeg læser, retter og godkender **altid** før posting.
- Du kan følge hele processen i repo’ets Pull Requests og commit-historik.

**Hver Reddit-post indeholder desuden denne faste disclaimer** (automatisk tilføjet af Agent 2):
> ---
> 🤖 *Denne post er genereret af LLM (Llama 3.1 70B) med human oversight via et open-source GitHub-projekt: https://github.com/LaZyDK/dkcyber-threat-monitor*
> Rå data er verificeret af mig før posting.

### Teknisk opsætning

- 100 % GitHub Actions (undtagen Telegram-scraper på VPS)
- Decoupled multi-agent workflows (ingen kæder)
- Gratis LLMs (GitHub Models + OpenRouter/Groq free tiers)
- Alt versioneret: raw → draft → final post

### Links

- Reddit: [r/dkcybersecurity](https://www.reddit.com/r/dkcybersecurity/)
- Issues & forslag: [Åbn et issue](../../issues)

**Made with ❤️ af en dansk cybersecurity-entusiast – og en flok venlige open-source LLMs.**

---

**Licens:** MIT  
**Sidst opdateret:** februar 2026