# Mod Setup — Arma Reforger (gecorrigeerd 2026-08-07)

## Wat er fout ging

De melding `Can't find '58D0FB3206B6F859' game addon!` betekende **niet** dat onze mod
niet gevonden werd. `58D0FB3206B6F859` is de GUID van de **base game zelf**
(`<game>\addons\data\ArmaReforger.gproj`). De engine kon zijn eigen game data niet laden
en crashte daarna met "Cannot initialize game project settings!" / "Engine Initialization Error".

Drie oorzaken:

1. **`-mod=` bestaat niet in Arma Reforger** (dat is Arma 3 / DayZ syntax). De engine
   negeert de parameter compleet. Officiele wiki (Arma_Reforger:Startup_Parameters):
   - `-addonsDir <pad>` — extra map waarin mods gezocht worden
   - `-addons <GUID>` — kommagescheiden lijst met mod IDs (GUID uit het .gproj bestand)
2. **Verkeerde working directory**: `start "" "<exe>"` erfde de CWD van de batchfile,
   waardoor de relatieve addon-map `./addons` naar `Q:\GAMES\Reforger-LLM-Squad\addons`
   wees i.p.v. naar de game folder. Fix: `start "" /d "<game_dir>" ...`
   (bewijs: 7/7 bat-launches faalden zo; launches via Steam werkten gewoon)
3. **Mod-format klopte niet**: `addon.json` / `gproj.conf` zijn verzonnen formaten — de
   engine leest ze niet. En de mod gebruikte de base-game GUID als eigen ID (conflict).
   Een echte addon = map met `addon.gproj` in GameProject-formaat, met een **eigen unieke
   GUID** en de base game als dependency.

## Correcte structuur

```
reforger_mod/
  addons/
    ReforgerLLMSquad/          <- mod folder (naam is vrij)
      addon.gproj              <- GameProject { ID, GUID, Dependencies }
      Scripts/Game/
        LLMBridge.c
```

Onze mod-GUID: `7E5A1C9B3D8F2406` (nooit `58D0FB3206B6F859` gebruiken — dat is de base game).

## Correcte launch (zie launch_reforger.bat)

```
start "" /d "Q:\SteamLibrary\steamapps\common\Arma Reforger" "Q:\SteamLibrary\steamapps\common\Arma Reforger\ArmaReforgerSteam.exe" -addonsDir "Q:\GAMES\Reforger-LLM-Squad\reforger_mod\addons" -addons "7E5A1C9B3D8F2406"
```

## Verifieren

Nieuwste log: `My Games\ArmaReforger\logs\logs_<timestamp>\console.log`

- GEEN `Game addon '58D0FB3206B6F859' not found` meer
- Log is veel groter dan ~1145 bytes (= oude crash-signatuur)
- Regels met `ReforgerLLMSquad` / geladen gproj
- Eventuele `SCRIPT (E)` compile errors in LLMBridge.c = volgende stap (F1.2):
  het script is nog niet als component geregistreerd en wordt dus ook nog nergens
  geinstantieerd — [LLMBridge] meldingen verschijnen pas na component-wiring.

## Aanbevolen (wiki: Arma_Reforger:Mod_Project_Setup)

Installeer **Arma Reforger Tools** (gratis op Steam) voor de Workbench: projecten aanmaken,
scripts debuggen, Play-mode testen en publiceren naar de Workshop. De Tools waren niet
gevonden in `Q:\SteamLibrary\steamapps\common\`.

## Bronnen

- https://community.bistudio.com/wiki/Arma_Reforger:Startup_Parameters
- https://community.bistudio.com/wiki/Arma_Reforger:Mod_Project_Setup
- https://feedback.bistudio.com/T164922 (zelfde "Check setup guidelines" melding)
- https://community.bistudio.com/wiki/Arma_Reforger:REST_API_Usage

---

## Status 2026-08-07 — OPGELOST & GEVERIFIEERD

De game start nu met de mod geladen en scripts gecompileerd (console.log ~20KB+,
hoofdmenu bereikt). Onderweg ook deze script-fouten gefixt:

| Fout | Oorzaak | Fix |
|---|---|---|
| `modclass LLMBridge : Component` | `modclass` bestaat niet in Enforce | `class LLMBridge` (wiring = F1.2) |
| regel 46 "Broken expression" | geneste classes (`class SquadMember` in `class LLMBridge`) mag niet | classes op file scope: `LLMSquadMember`, `LLMWaypoint` (ook hernoemd i.v.m. engine class `Waypoint`) |
| `new RestContext()` / `SetMethod` / `Start` | verzonnen API | echte API: `GetGame().GetRestApi().GetContext(url)` + `GET(cb, path)` / `POST(cb, path, body)` + `RestCallback` |
| "Method '~RestContext' is private" | `ref RestContext` = ownership, destructor is private | non-ref: `RestContext m_Rest;` |
| "Undefined function 'World.GetGameTime'" | bestaat niet in Reforger | eigen tijd-accumulatie via `timeslice` in `Update()` |

Resterende warnings (bewust gelaten, werken gewoon):
- `'OnSuccess'/'OnError' is obsolete: Use RestCallback.SetOnSuccess()` — deprecated
  override-stijl, functioneel. Opruimen = later.

## Volgende stap (F1.2 uit PROJECT_PLAN)

`LLMBridge` wordt nog nergens geinstantieerd -> er verschijnen dus nog GEEN
`[LLMBridge]` regels in-game. Wiring: `modded class SCR_BaseGameMode` die bij
OnGameStart een `LLMBridge` maakt, `Activate()` aanroept en via
`GetGame().GetCallqueue().CallLater()` periodiek `Update(timeslice)` aanroept.
