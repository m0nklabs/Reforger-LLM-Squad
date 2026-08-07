<!-- Canonical source of truth: AGENTS.md (repo root). This file is Copilot-native and deliberately compact. -->
# GitHub Copilot Instructions

Read **AGENTS.md** (repo root) first — it is the source of truth for all AI tools in this repo.

## ⛔ 3 fatal pitfalls (already went wrong once — do not repeat)
1. `-mod=` does NOT exist in Reforger → load mods with `-addonsDir <path> -addons <GUID>`.
2. Start the game ONLY via `launch_reforger.bat` (it sets working directory = game dir; otherwise "Missing Addon 58D0FB3206B6F859" + Engine Init Error).
3. GUID `58D0FB3206B6F859` = the base game; our mod = `7E5A1C9B3D8F2406`.

## Core rules
1. Verify EVERYTHING empirically: kill game → `launch_reforger.bat` → ~50s → `powershell -NoProfile -File scripts\check_latest_log.ps1`. Never claim "fixed" without log evidence.
2. Enforce: no nested classes; `class`/`modded class`; no `ref RestContext`; no `World.GetGameTime()`. See `docs/skills/enforce-script.md`.
3. REST in-game: `GetGame().GetRestApi().GetContext(url)` + `GET/POST(cb, ...)` with `RestCallback`.
4. Route/port sync game↔bridge: bridge = port 5001; routes must match `python_bridge/main.py`.
5. Never commit secrets: `python_bridge/config.json` is gitignored (template: `config.example.json`). No API keys in docs.

Detail skills (read when working in that area):
- `docs/skills/arma-reforger-modding.md` — addon structure, GUIDs, launch parameters
- `docs/skills/enforce-script.md` — Enforce language rules + REST pattern
- `docs/skills/reforger-debugging.md` — console.log signatures + test cycle

Language: English everywhere (code, comments, docs, commits).
