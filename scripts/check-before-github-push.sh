#!/usr/bin/env bash
# Run from repo root: ./scripts/check-before-github-push.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== Code Atlas: pre-push secret / hygiene check =="
BAD=0

for f in config/config.json config/notifications_config.json config/repos_config.json \
         config/indexing_paths.json config/ai_config.json .env .env.local; do
  if git ls-files --error-unmatch "$f" &>/dev/null; then
    echo "ERROR: $f is tracked — remove from git before pushing (use *.example only)."
    BAD=1
  fi
done

# Machine dumps should not be tracked
for f in config/services_mapping.json config/skip_repos.json; do
  if git ls-files --error-unmatch "$f" &>/dev/null; then
    echo "ERROR: $f is tracked — use ${f}.example and .gitignore the real file."
    BAD=1
  fi
done

if command -v rg &>/dev/null; then
  if rg -l 'glpat-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{36,}|xox[baprs]-|hooks\.slack\.com/services/[A-Za-z0-9/]+' \
      --glob '!*.md' --glob '!*.example' --glob '!check-before-github-push.sh' \
      --glob '!docs/**' . 2>/dev/null | head -20 | grep -q .; then
    echo "ERROR: Possible tokens or Slack webhook paths found. Inspect with:"
    echo "  rg 'glpat-|ghp_|hooks\\.slack\\.com/services/' --glob '!*.example'"
    BAD=1
  fi
else
  echo "(Optional: install ripgrep 'rg' for deeper scans.)"
fi

if [[ "$BAD" -ne 0 ]]; then
  exit 1
fi
echo "OK — no obvious tracked secrets. Review docs/GITHUB_PUBLISH.md before push."
exit 0
