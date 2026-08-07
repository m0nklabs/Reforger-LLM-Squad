# Skill: Arma Reforger — mod-structuur & lokaal laden

> Hard-won lessen uit de debug-sessie van 2026-08-07 (build 190965), empirisch geverifieerd.
> Bronnen: BI-wiki `Arma_Reforger:Startup_Parameters`, `:Mod_Project_Setup`, feedback ticket T164922.

## 1. Minimale geldige addon

```text
<addonsDir>/
  MijnMod/                    <- mapnaam is VRIJ (hoeft geen GUID te zijn)
    addon.gproj               <- verplicht, GameProject-formaat (GEEN json!)
    Scripts/
      Game/                   <- module "Game" (hercompileert ALLES, zie enforce-script skill)
        MijnScript.c
```

`addon.gproj` voorbeeld (copy-paste-veilig):
```
GameProject {
 ID "MijnMod"
 GUID "7E5A1C9B3D8F2406"
 TITLE "Mijn Mod"
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

## 2. GUID-regels

- GUID = 16 hex-tekens, UNIEK per addon. Zelf verzinnen is prima (Workbench genereert er normaal één).
- **Bekende gereserveerde GUIDs — nooit hergebruiken:**
  | GUID | Addon |
  |---|---|
  | `58D0FB3206B6F859` | **ArmaReforger base game data** (`<game>\addons\data\ArmaReforger.gproj`) |
  | `5614BBCCBB55ED1C` | `core` (`<game>\addons\core\core.gproj`) |
  | `7E5A1C9B3D8F2406` | onze mod `ReforgerLLMSquad` (deze repo) |
- Base game dependency declareer je in `Dependencies { "58D0FB3206B6F859" }` — zo doen alle BI SampleMods het.
- Terugvinden: console.log sectie `Available addons:` toont `gproj: '<pad>' guid: '<GUID>'` per gevonden addon.

## 3. Lokaal laden ZONDER Workshop (de enige correcte manier)

```bat
start "" /d "<game_dir>" "<game_dir>\ArmaReforgerSteam.exe" -addonsDir "<parent-van-modmap>" -addons "<GUID>"
```

- `-addonsDir <pad>` — extra zoekmap (mods worden ook gezocht in `<exeDir>/addons` en `profile/addons`)
- `-addons <id1>,<id2>` — kommagescheiden mod IDs (GUID = preferred; Project ID mag ook)
- ⚠️ **`-mod=` bestaat NIET** (Arma 3/DayZ-syntax). De engine negeert hem compleet — geen warning.
- ⚠️ **`start "" /d "<game_dir>"` is VERPLICHT-achtig**: zonder `/d` erft het proces de CWD van je
  shell/bat, en de RELATIEVE addon-dir `./addons` wijst dan fout → de engine vindt z'n eigen
  base game niet → `Can't find '58D0FB3206B6F859' game addon! Check setup guidelines!`
  → `Cannot initialize game project settings!` → Engine Initialization Error.
  Die GUID in de melding is dus de BASE GAME, niet jouw mod. Lees de melding letterlijk.
- Lokale unpacked mods verschijnen NIET in de in-game mod manager — dat is normaal.

## 4. Unpacked vs packed

| | Unpacked (dev) | Packed (Workshop) |
|---|---|---|
| Vorm | map met `addon.gproj` + losse bestanden | `.pak` bestanden, map per GUID |
| Scripts | gecompileerd vanaf source bij game-start | meegepacked |
| `resourceDatabase.rdb` warning | onschuldig (cache wordt aangemaakt) | — |
| Laden | `-addonsDir` + `-addons`, of Workbench Play | Workshop/in-game manager |

## 5. Aanbevolen tooling

- **Arma Reforger Tools** (gratis op Steam) = Workbench: live script-compile met foutmarkeringen,
  Play-mode, publiceren naar Workshop. Voor serieuze mod-dev is de Workbench-scripteditor een
  VEEL snellere feedback-loop dan game-launches.
- Deze repo werkt bewust CLI-first (geen Workbench nodig voor laden/testen).
