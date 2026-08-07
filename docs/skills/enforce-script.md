# Skill: Enforce script (Arma Reforger) — compiler-lessen

> Lessen uit echte compile-fouten, 2026-08-07 (build 190965). Elke regel hier is een keer
> foutgegaan en via `console.log` `SCRIPT (E)` gediagnosticeerd.

## 1. Module-systeem & naamgeving

- `Scripts/<Module>/` bepaalt de script-module. `Scripts/Game/x.c` → module `Game`.
- Bij een unpacked script-addon wordt de HELE Game-module hercompileerd: base-game sources
  (uit `data.pak`) + jouw files. Base-game errors ná jouw errors = cascade — fix jouw file eerst.
- Class-namen zijn globaal per module → ALTIJD prefixen (wij gebruiken `LLM`). Botsing met
  engine-classes (bv. `Waypoint`) = compile error.

## 2. Taalregels (met fout → fix)

| Fout | Waarom | Fix |
|---|---|---|
| `modclass X : Y` | keyword bestaat niet | `class X` of `modded class BestaandeClass` |
| `class B` BINNEN `class A` | geneste classes bestaan niet → "Broken expression" op die regel, "Unmatched brackets"/"Invalid statement ':'" verderop | ALLE classes op file scope |
| `ref RestContext x;` | destructor is private ("Method '~RestContext' is private") | non-ref handle: `RestContext x;` — RestApi bezit het object |
| `GetGame().GetWorld().GetGameTime()` | bestaat niet in Reforger ("Undefined function 'World.GetGameTime'") | eigen timer: `m_fTime += timeslice;` in een Update-loop (timeslice = seconden) |
| `override` op methode zonder base class | geen base → geen override | `override` weglaten |
| ternary `(a ? "x" : y)` in string-concat | fragiel in parser | if/else met tijdelijke variabele |
| `"txt" + mijnBool` | bool-concat is fragiel | helper: `if (b) return "true"; return "false";` |
| `vector v = "0 0 0";` | — | WERKT (string→vector conversie bestaat) |

- `Print("...")` → `console.log` (onze runtime-logging). Geen `throw` gebruiken voor flow.
- `ref` = ownership-reference; weglaten = non-owning pointer. Eigen classes: `ref` is prima.
- Constructors: `void ClassName(args)`. `new array<ref T>` zonder haakjes werkt.

## 3. REST API (de ECHTE API — wiki: Arma_Reforger:REST_API_Usage)

Alleen GET en POST. Patroon dat compileert én werkt:

```cs
class MijnCallback : RestCallback
{
    override void OnSuccess(string data, int dataSize)
    {
        Print("OK: " + data);
    }
    override void OnError(int errorCode)
    {
        Print("ERROR " + errorCode);
    }
}

// ergens in je logica:
RestContext ctx = GetGame().GetRestApi().GetContext("http://127.0.0.1:5001"); // NON-ref member!
ctx.GET(new MijnCallback(), "/health");
ctx.POST(new MijnCallback(), "/sitrep", "{\"key\": \"value\"}");
```

- `GetContext(baseUrl)` — daarna zijn paths relatief (`/health`).
- Overrides `OnSuccess`/`OnError` geven `obsolete`-WARNINGS (geen errors): de moderne stijl is
  `RestCallback.SetOnSuccess(...)`. Overrides werken gewoon; warnings zijn acceptabel.
- Callbacks `new`en per request is het gangbare patroon.
- FOUT patroon (verzonnen, compileert niet): `new RestContext()`, `SetURL()`, `SetMethod(RestMethod.POST)`, `.Start()`.

## 4. Verifiëren

Compile-status staat in de nieuwste `console.log`:
- GOED: `Module: Game; loaded Nx files` regels, geen `Can't compile "Game" script module!`
- FOUT: `SCRIPT (E): @"scripts/Game/<file>.c,<regel>": <melding>` — regelnummers zijn accuraat.
