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

GET and POST only. Two critical bugs discovered F1.3 (2026-08-09):

### Bug 1: Callback GC (callbacks never fire)

If you create a callback inline, the Enforce GC destroys it before the async HTTP
response arrives. The HTTP request is sent, the server returns 200, but `OnSuccess`
and `SetOnSuccess` handlers NEVER fire.

**WRONG** (callback GC'd before response):
```cs
ctx.GET(new MyCallback(), "/health");  // callback object has no ref → GC'd
```

**RIGHT** (callback stored in ref array):
```cs
class MyBridge
{
    ref array<ref MyCallback> m_aActiveCallbacks;  // keeps callbacks alive

    protected MyCallback CreateCallback(string endpoint)
    {
        MyCallback cb = new MyCallback(this, endpoint);
        m_aActiveCallbacks.Insert(cb);
        while (m_aActiveCallbacks.Count() > 20)
            m_aActiveCallbacks.RemoveOrdered(0);
        return cb;
    }
}
```

### Bug 2: POST body is empty (body never transmits)

`ctx.POST(callback, path, body)` sends the HTTP request, but the body parameter
**never arrives** at the server. The server sees a POST with `Content-Length: 0`.

**WRONG** (body never arrives):
```cs
ctx.POST(cb, "/sitrep", "{\"key\": \"value\"}");  // server sees empty body
```

**RIGHT** (send data via GET query param):
```cs
ctx.GET(cb, "/sitrep?data=" + UrlEncode(jsonString));  // server receives ?data=...
```

Enforce has no built-in URL encoder — write your own (see `LLMBridge.UrlEncode()`).

### Modern callback API

Both `SetOnSuccess` (modern) and `OnSuccess` (deprecated override) work once
the callback survives GC. Using both is safe:

```cs
class MyCallback : RestCallback
{
    void MyCallback(MyBridge owner, string endpoint) { ... }

    // Modern API — set in constructor
    void MyCallback(...) {
        SetOnSuccess(SuccessHandler);
        SetOnError(ErrorHandler);
    }

    void SuccessHandler(RestCallback cb = null) { ... }  // RestCallbackFunc signature
    void ErrorHandler(RestCallback cb = null) { ... }

    // Deprecated overrides — also fire (obsolescence warnings expected)
    override void OnSuccess(string data, int dataSize) { ... }
    override void OnError(int errorCode) { ... }
}
```

### Full working pattern

```cs
RestContext ctx = GetGame().GetRestApi().GetContext("http://127.0.0.1:5001"); // NON-ref member!
MyCallback cb = CreateCallback("/health");  // stored in ref array → survives GC
ctx.GET(cb, "/health");                      // GET works, callbacks fire
ctx.GET(cb, "/sitrep?data=" + UrlEncode(json));  // data via query param
```

- `GetContext(baseUrl)` — after that, paths are relative (`/health`).
- WRONG pattern (invented, does not compile): `new RestContext()`, `SetURL()`, `SetMethod(RestMethod.POST)`, `.Start()`.
- Reference: ARExplorer (arexplorer.zeroy.com) — RestCallback class, RestCallbackFunc typedef.

## 4. How to verify

Compile status lives in the newest `console.log`:
- GOOD: `Module: Game; loaded Nx files` lines, no `Can't compile "Game" script module!`
- BAD: `SCRIPT (E): @"scripts/Game/<file>.c,<line>": <message>` — line numbers are accurate.
