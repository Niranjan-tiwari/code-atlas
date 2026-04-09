# Publishing to GitHub safely

For **full self-hosted setup** (indexing, API, production hardening), see **[`SELF_HOSTING.md`](SELF_HOSTING.md)**.

## Secrets audit (do this before `git push`)

| Risk | What to do |
|------|------------|
| **Slack webhooks** in `config/config.json` or `notifications_config.json` | **Rotate/revoke** in Slack if they were ever committed or shared. Use env-specific webhooks only locally. |
| **API keys** | Never commit. Use `export OPENAI_API_KEY=...`, GitHub **Actions secrets**, or **Dependabot**-style secret scanning. |
| **`GITLAB_TOKEN`** | Environment variable or CI secret only. |
| **`repos_config.json`** | Lists internal clone URLs — kept out of git via `.gitignore`. Use `repos_config.json.example`. |
| **`services_mapping.json`** | Was a full systemd dump (RMM, remote desktop, etc.) — **must not** be committed. Use `services_mapping.json.example`; real file is gitignored. |
| **`skip_repos.json`** | Can contain internal repo names — gitignored; use `skip_repos.json.example`. |
| **`indexing_paths.json`** | Your local workspace roots — gitignored; use `indexing_paths.json.example`. |
| **`ai_config.json`** | LLM endpoints / keys — gitignored; use `ai_config.json.example`. |
| **`data/qdrant_db`** | Large + may embed code; ignored. Each clone rebuilds index. |
| **Personal paths** (`/home/you/...`) | Use `config.json.example` as template. |

## Files this repo ignores (local-only)

See root `.gitignore`: `config/config.json`, `ai_config.json`, `notifications_config.json`, `code-atlas.service`, `data/`, `logs/`, `.env*`, etc.

After pulling:

```bash
cp config/config.json.example config/config.json
cp config/ai_config.json.example config/ai_config.json
cp config/notifications_config.json.example config/notifications_config.json
cp config/indexing_paths.json.example config/indexing_paths.json
cp .env.example .env
cp config/services_mapping.json.example config/services_mapping.json
cp config/skip_repos.json.example config/skip_repos.json
# optional: cp code-atlas.service.example /etc/systemd/system/your-worker.service
```

## First-time push checklist

1. `./scripts/check-before-github-push.sh` — optional automated check.
2. `git status` — confirm no `config.json`, `ai_config.json`, `services_mapping.json`, `skip_repos.json`, `indexing_paths.json`, `*.log`, `data/qdrant_db`, `.env`, or tokens.
3. Optional: `git log -p -- config/config.json` — if this file was ever committed, **rotate Slack webhook** and consider `git filter-repo` / BFG to purge history before open-sourcing. Same for `indexing_paths.json` if it ever held real paths.
4. Create empty repo on GitHub with your chosen name → add remote → push.

## Suggested GitHub repo name

This project is **Code Atlas** — a good matching remote name is **`code-atlas`**.  
Folder name and GitHub repo name can differ; set the remote name under **Settings → General** on GitHub.
