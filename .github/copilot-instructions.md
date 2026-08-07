<!-- Canonical source of truth: AGENTS.md (repo root). Dit bestand is Copilot-native en bewust compact. -->
# GitHub Copilot Instructions

Lees eerst **AGENTS.md** (repo root) — dat is de source of truth voor alle AI-tools in deze repo.

Kernregels (rationale + details: AGENTS.md en `docs/skills/`):
1. GUID `58D0FB3206B6F859` = de base game. Onze mod-GUID = `7E5A1C9B3D8F2406` — nooit verwisselen.
2. Mods laden met `-addonsDir <pad> -addons <GUID>` (NIET `-mod=`); working dir = game-dir.
3. Test = empirisch: kill game → `launch_reforger.bat` → ~50s → nieuwste `console.log` lezen. Nooit "fixed" claimen zonder log-bewijs.
4. Enforce: geen geneste classes; `class`/`modded class`; geen `ref` op `RestContext`; geen `World.GetGameTime()`.
5. REST in-game: `GetGame().GetRestApi().GetContext(url)` + `GET/POST(cb, ...)` met `RestCallback`.
6. Route/poort-sync game↔bridge: bridge = poort 5001; routes moeten matchen met `python_bridge/main.py`.
7. Geen secrets committen: `python_bridge/config.json` is gitignored (template: `config.example.json`).

Detail-skills (lees bij werk aan dat gebied):
- `docs/skills/arma-reforger-modding.md` — addon-structuur, GUIDs, launch-parameters
- `docs/skills/enforce-script.md` — Enforce-taalregels + REST-patroon
- `docs/skills/reforger-debugging.md` — console.log-signatures + test-cyclus
