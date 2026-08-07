# Skill: Enforce script (Arma Reforger) — compiler lessons

> Lessons from real compile failures, 2026-08-07 (build 190965). Every rule here went wrong
> once and was diagnosed via `SCRIPT (E)` lines in `console.log`.

## 1. Module system & naming

- `Scripts/<Module>/` determines the script module. `Scripts/Game/x.c` → module `Game`.
- With an unpacked script addon, the ENTIRE Game module is recompiled: base-game sources
  (from `data.pak`) + your files. Base-game errors AFTER your errors = cascade — fix your file first.
- Class names are global per module → ALWAYS prefix (we use `LLM`). Colliding with
  engine classes (e.g. `Waypoint`) = compile error.

## 2. Language rules (failure → fix)

| Failure | Why | Fix |
|---|---|---|
| `modclass X : Y` | keyword does not exist | `class X` or `modded class ExistingClass` |
| `class B` INSIDE `class A` | nested classes do not exist → "Broken expression" at that line, "Unmatched brackets"/"Invalid statement ':'" further down | ALL classes at file scope |
| `ref RestContext x;` | destructor is private ("Method '~RestContext' is private") | non-ref handle: `RestContext x;` — RestApi owns the object |
| `GetGame().GetWorld().GetGameTime()` | does not exist in Reforger ("Undefined function 'World.GetGameTime'") | own timer: `m_fTime += timeslice;` in an Update loop (timeslice = seconds) |
| `override` on a method without base class | no base → no override | drop `override` |
| ternary `(a ? "x" : y)` inside string concat | fragile in the parser | if/else with a temp variable |
| `"text" + myBool` | bool concat is fragile | helper: `if (b) return "true"; return "false";` |
| `vector v = "0 0 0";` | — | WORKS (string→vector conversion exists) |

- `Print("...")` → `console.log` (our runtime logging). Do not use `throw` for control flow.
- `ref` = ownership reference; omitting it = non-owning pointer. For your own classes `ref` is fine.
- Constructors: `void ClassName(args)`. `new array<ref T>` without parentheses works.

## 3. REST API (the REAL API — wiki: Arma_Reforger:REST_API_Usage)

GET and POST only. A pattern that compiles AND works:

```cs
class MyCallback : RestCallback
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

// somewhere in your logic:
RestContext ctx = GetGame().GetRestApi().GetContext("http://127.0.0.1:5001"); // NON-ref member!
ctx.GET(new MyCallback(), "/health");
ctx.POST(new MyCallback(), "/sitrep", "{\"key\": \"value\"}");
```

- `GetContext(baseUrl)` — after that, paths are relative (`/health`).
- The `OnSuccess`/`OnError` overrides produce `obsolete` WARNINGS (not errors): the modern style is
  `RestCallback.SetOnSuccess(...)`. Overrides still work; warnings are acceptable.
- Creating a fresh callback per request is the common pattern.
- WRONG pattern (invented, does not compile): `new RestContext()`, `SetURL()`, `SetMethod(RestMethod.POST)`, `.Start()`.

## 4. How to verify

Compile status lives in the newest `console.log`:
- GOOD: `Module: Game; loaded Nx files` lines, no `Can't compile "Game" script module!`
- BAD: `SCRIPT (E): @"scripts/Game/<file>.c,<line>": <message>` — line numbers are accurate.
