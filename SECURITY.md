# Security Policy

## Supported Versions
Only the latest `main` branch receives security updates.

## Reporting a Vulnerability
- Do NOT post secrets or partial keys in issues/PRs/chat.
- Open a private issue or contact the maintainer directly.
- If you find a leaked token in this repo's history, report it immediately — it will be rotated.

## Practices
- `.env` is `.gitignore`d; never commit real keys.
- Replace leaked fragments with `<PLACEHOLDER>` before pushing.
- Requesty / OpenRouter / Discord / Gemini / Serper keys must be rotated if exposed.

## Known Status (2026-10-01)
- `.env` placeholders applied; original fragments rotated out.
- Requesty API exposure from prior session: rotation not yet confirmed.
- No hardcoded secrets found in `core/`, `bot/`, `llm/`.
