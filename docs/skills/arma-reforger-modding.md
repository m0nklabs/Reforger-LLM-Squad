# Skill: Arma Reforger — mod structure & local loading

> Hard-won lessons from the 2026-08-07 debug session (build 190965), empirically verified.
> Sources: BI wiki `Arma_Reforger:Startup_Parameters`, `:Mod_Project_Setup`, feedback ticket T164922.

## 1. Minimal valid addon

```text
<addonsDir>/
  MyMod/                      <- folder name is FREE (does not have to be a GUID)
    addon.gproj               <- required, GameProject format (NOT json!)
    Scripts/
      Game/                   <- module "Game" (recompiles EVERYTHING, see enforce-script skill)
        MyScript.c
```

`addon.gproj` example (copy-paste safe):
```
GameProject {
 ID "MyMod"
 GUID "7E5A1C9B3D8F2406"
 TITLE "My Mod"
 Dependencies {
  "58D0FB3206B6F859"
 }
 Configurations {
  GameProjectConfig PC {
  }
  GameProjectConfig HEADLESS {
  }
 }
}
```

## 2. GUID rules

- GUID = 16 hex characters, UNIQUE per addon. Making one up is fine (Workbench normally generates it).
- **Known reserved GUIDs — never reuse:**
  | GUID | Addon |
  |---|---|
  | `58D0FB3206B6F859` | **ArmaReforger base game data** (`<game>\addons\data\ArmaReforger.gproj`) |
  | `5614BBCCBB55ED1C` | `core` (`<game>\addons\core\core.gproj`) |
  | `7E5A1C9B3D8F2406` | our mod `ReforgerLLMSquad` (this repo) |
- Declare the base game dependency via `Dependencies { "58D0FB3206B6F859" }` — all BI SampleMods do this.
- Finding GUIDs: the console.log section `Available addons:` shows `gproj: '<path>' guid: '<GUID>'` per addon found.

## 3. Loading a local mod WITHOUT the Workshop (the only correct way)

```bat
start "" /d "<game_dir>" "<game_dir>\ArmaReforgerSteam.exe" -addonsDir "<parent-of-modfolder>" -addons "<GUID>"
```

- `-addonsDir <path>` — extra search dir (mods are also searched in `<exeDir>/addons` and `profile/addons`)
- `-addons <id1>,<id2>` — comma-separated mod IDs (GUID = preferred; Project ID also works)
- ⚠️ **`-mod=` does NOT exist** (Arma 3/DayZ syntax). The engine ignores it completely — no warning.
- ⚠️ **`start "" /d "<game_dir>"` is effectively REQUIRED**: without `/d` the process inherits your
  shell's CWD, and the RELATIVE addon dir `./addons` then points the wrong way → the engine cannot
  find its own base game → `Can't find '58D0FB3206B6F859' game addon! Check setup guidelines!`
  → `Cannot initialize game project settings!` → Engine Initialization Error.
  That GUID in the message is the BASE GAME, not your mod. Read the message literally.
- Local unpacked mods do NOT appear in the in-game mod manager — that is normal.

## 4. Unpacked vs packed

| | Unpacked (dev) | Packed (Workshop) |
|---|---|---|
| Form | folder with `addon.gproj` + loose files | `.pak` files, one folder per GUID |
| Scripts | compiled from source at game start | shipped inside the pak |
| `resourceDatabase.rdb` warning | harmless (cache gets created) | — |
| Loading | `-addonsDir` + `-addons`, or Workbench Play | Workshop / in-game manager |

## 5. Recommended tooling

- **Arma Reforger Tools** (free on Steam) = Workbench: live script compilation with error markers,
  Play mode, Workshop publishing. For serious mod dev the Workbench script editor is a MUCH
  faster feedback loop than game launches.
- This repo deliberately works CLI-first (no Workbench needed for loading/testing).
