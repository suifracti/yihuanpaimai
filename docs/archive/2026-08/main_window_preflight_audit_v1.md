# 0.67 Desktop Alpha — Milestone 1 Main Window Preflight Audit v1

## 0. Scope and verdict

**Audit baseline (FACT):** repository `HEAD = 4fc375c04c5a4ffacbc1cb2c0f2348a5fb72d307`.

**Scope (FACT):** this is a read-only architecture and lifecycle audit. No Main Window, Solver, Overlay, vision, History, or Benchmark code was changed.

**Milestone 1 verdict (RECOMMENDATION):** use a native, standard WinForms Main Window as the application-lifetime owner; keep the existing DirectComposition Overlay and its current Solver runtime intact as a helper window. Run `Application.Run(mainWindow)`. The Main Window should only show/hide the existing Overlay and own orderly shutdown. **Milestone 1 Main Window must not load `auction_engine_v06.js`, `solver_core_v06.js`, or create another Solver runtime. A Main Window WebView2 is not required for this first slice.**

This is candidate **A, reduced to its minimum native shell**. It preserves the only current final Solver execution path instead of migrating Solver ownership during a window-lifecycle milestone.

---

## 1. Current EXE lifecycle

### 1.1 Entry and packaging

- **FACT:** PyInstaller builds the windowed EXE from `app/main.py`; the spec declares `console=False` and the output name `异环拍卖助手` (`app/异环拍卖助手.spec:41-83`).
- **FACT:** the normal entry calls `main()`. The same executable with `--vision-worker` calls `vision_capture_worker()` instead (`app/main.py:1635-1639`).
- **FACT:** the currently executed source path loads `core/overlay_alpha.html` (`app/main.py:1502`), not `core/tactical_hud.html`.
- **FACT — packaging debt discovered:** the checked-in spec includes `tactical_hud.html` and `auction_engine_v06.js`, but does not list the active `overlay_alpha.html` or its required `v06_adapter.js` (`app/异环拍卖助手.spec:8-18`; `core/overlay_alpha.html:7-8`). A clean build from this spec therefore does not have a source-declared guarantee that the active page and adapter are bundled. This is a build-input inconsistency, not a reason to change Solver ownership.

### 1.2 Process/thread tree

```text
异环拍卖助手.exe (parent process)
│
├─ Python main thread
│  ├─ main()
│  ├─ run_hud_app()
│  └─ waits on GUI STA thread with t_gui.Join()
│
├─ daemon icon-injector thread
│
├─ daemon WebSocket-bus thread
│  └─ asyncio loop + ws://127.0.0.1:8766
│     └─ waits indefinitely on asyncio.Future()
│
└─ .NET STA GUI thread
   ├─ DirectCompositionHudForm (currently the Overlay and only top-level app form)
   ├─ CoreWebView2Environment
   ├─ DirectComposition + CoreWebView2CompositionController
   ├─ overlay_alpha.html
   └─ WinForms Application.Run(overlayForm)

after HUD-ready report:

异环拍卖助手.exe --vision-worker (child process)
├─ NTEVisionPipeline + capture/OCR asyncio loop
├─ daemon live-shadow worker thread
└─ persistent Node child when Shadow is warmed/used
   └─ core/live_shadow_runtime.js
```

Evidence:

- **FACT:** `main()` starts the icon and WebSocket threads as daemon threads, then enters `run_hud_app()` (`app/main.py:1614-1632`).
- **FACT:** `run_hud_app()` creates a separate .NET `Thread`, marks it STA, starts it, and blocks the Python main thread with `Join()` (`app/main.py:1608-1611`).
- **FACT:** the STA thread creates and shows `DirectCompositionHudForm`, creates one `CoreWebView2Environment`, initializes the DirectComposition controller, then calls `Application.Run(form)` (`app/main.py:1508-1606`).
- **FACT:** Overlay readiness calls `start_vision_worker()`, which starts the same EXE with `--vision-worker` (`app/main.py:1239-1260`, `app/main.py:1337-1374`).
- **FACT:** the worker owns `NTEVisionPipeline.current_context`, frame processing, settlement archiving, and WS publication (`app/main.py:829-1125`).
- **FACT:** live Shadow starts a persistent Node process through `core/live_shadow.py:_start_runtime()` and communicates over line-delimited stdin/stdout (`core/live_shadow.py:277-315`).

### 1.3 Current shutdown path

- **FACT:** ordinary Overlay close triggers its `FormClosing` callback, whose only explicit action is `stop_vision_worker()`; `Application.Run(form)` then returns and the STA thread ends (`app/main.py:1512-1515`, `app/main.py:1604-1611`).
- **FACT:** `stop_vision_worker()` requests settlement flush, waits 0.4 seconds, terminates the child, and kills it only on failure (`app/main.py:1377-1408`).
- **FACT:** when normal execution returns from `run_hud_app()`, `main()` returns. The icon and WS threads are daemon threads, so process termination ends them; the WS loop has no explicit stop signal (`app/main.py:370-382`).
- **FACT:** the HTML/native `exit_app` path closes the Overlay and then calls `os._exit(0)` (`app/main.py:1262-1275`). This bypasses normal Python unwinding.
- **FACT:** `flush_draft_save_sync()` exists but is not called by either current FormClosing or `exit_app` (`app/main.py:471-479`).
- **FACT:** `DirectCompositionHudForm` has no explicit `OnFormClosed`/`Dispose` override for its WinForms timer, composition controller, or DComp objects in the checked-in C# source (`app/DirectCompositionHost.cs:194-405`). Microsoft documents `CoreWebView2Controller.Close()` as the safe shutdown path for associated WebView2 processes.
- **INFERENCE:** current shutdown is process-terminating but only partially orderly. A Main Window owner must not merely move `Application.Run`; it needs one idempotent shutdown coordinator so Overlay callbacks cannot race disposed windows and draft/child resources are not abandoned.

---

## 2. Solver execution ownership

### 2.1 Final production Solver call chain in the currently loaded Alpha

```text
core/overlay_alpha.html
  handleLocalInput(element)
    -> scheduleLocalSolver()
       -> collectFacts()
       -> paintResult({ solverInput })
          -> window.AuctionEngineV06.solveAuctionPipeline(solverInput)
             -> solveExactStatesSync(ctx)
          -> transient engineResult
          -> paint DOM fields
```

Concrete chain:

- **FACT:** the active page loads `auction_engine_v06.js` and `v06_adapter.js` (`core/overlay_alpha.html:7-8`).
- **FACT:** manual input schedules a 180 ms local Solver timer and calls `paintResult()` (`core/overlay_alpha.html:903-927`).
- **FACT:** `paintResult()` calls `window.AuctionEngineV06.solveAuctionPipeline()` and directly paints its returned `formalValue`, `rawShadow`, `decision`, and `solverStatus` (`core/overlay_alpha.html:961-1024`).
- **FACT:** `solveAuctionPipeline()` calls `solveExactStatesSync()` inside `auction_engine_v06.js` (`core/auction_engine_v06.js:1649-1708`).
- **FACT:** a payload returned from Python is also passed back into `paintResult()` by `applyManualState()`; this recomputes in the same Overlay WebView runtime (`core/overlay_alpha.html:1026-1073`).

**Conclusion (FACT):** for the currently loaded Manual Alpha, the Overlay WebView is the **final Solver execution owner**, not a passive consumer. Its output is transient WebView state/DOM; Python does not persist a canonical Solver result.

### 2.2 What Python owns

```text
Overlay input
  -> WebMessage: manual_facts
  -> app/main.py:on_web_message
  -> HudJsApi.apply_manual_facts()
  -> app/main.py:apply_manual_facts()
  -> module-level CURRENT_MATCH.apply_facts()
  -> CurrentMatch snapshot / Canonical v7 facts
  -> canonical_to_v06_solver_input()
  -> payload broadcast to Overlay
  -> Overlay paintResult()
  -> JS Solver
```

- **FACT:** `CURRENT_MATCH = CurrentMatch()` is constructed once at module scope in the parent process (`app/main.py:104-109`).
- **FACT:** `CurrentMatch` explicitly holds facts only and “does not talk to Solver, OCR, or Shadow” (`core/current_match.py:2-6`).
- **FACT:** `apply_manual_facts()` mutates `CURRENT_MATCH`, schedules draft persistence, creates a Canonical v7 snapshot, converts it to a v0.6 Solver input, and updates `LATEST_PAYLOAD` (`app/main.py:482-555`). It does not call a Solver.
- **FACT:** `LATEST_PAYLOAD` is a mutable, field-wise WS cache (`dict.update`), not a typed current-match object or an atomic Solver-result SOT (`app/main.py:100`, `app/main.py:300-368`).

**Conclusion (FACT):** Python owns the authoritative manual fact draft; it does not own final Solver execution or a final Solver-result record.

### 2.3 Node Shadow and `solver_core_v06.js`

```text
vision_capture_worker()
  -> NTEVisionPipeline.process_frame()
  -> build_in_auction_hud_payload(ctx)
  -> live_shadow.attach_live_shadow(ctx)          [non-blocking]
  -> _shadow_worker_loop()
  -> compute_live_probability_profile()
  -> _runtime_compute()
  -> node core/live_shadow_runtime.js
       -> require(auction_engine_v06.js)
       -> eval(solver_core_v06.js) for legacy helper functions
       -> engine.solveExactStatesSync()
       -> expandStatesForValuation/stateComponents/candidateStateWeight
       -> shadow_profile_v06.buildProbabilityProfile()
  -> probabilityProfile returned to vision payload
```

- **FACT:** Node Shadow calls `auction_engine_v06.js:solveExactStatesSync()` and produces a compact historical probability profile (`core/live_shadow_runtime.js:109-173`).
- **FACT:** it also reads/evaluates `solver_core_v06.js` to expose `expandStatesForValuation`, `stateComponents`, `candidateStateWeight`, and `redProbabilityProfile` helpers (`core/live_shadow_runtime.js:40-60`). Therefore `solver_core_v06.js` **does still have a production call chain**, but only through the live historical Shadow sidecar.
- **FACT:** `attach_live_shadow()` is deliberately non-blocking and returns the last completed profile while a daemon worker computes newer data (`core/live_shadow.py:347-449`).
- **FACT:** the current `overlay_alpha.html` WS handler only applies messages marked `manual_alpha_state`, `manualMode`, or `canonical`; raw live-vision payloads are ignored by this page (`core/overlay_alpha.html:1206-1232`).
- **INFERENCE:** Node Shadow is neither a test-only verifier nor the final Solver authority. It is a production **live-vision probability/evidence sidecar**. It computes exact states as an ingredient, but does not own the current Manual Alpha decision result. In the presently loaded page its live payload is not consumed; reconnecting live vision is explicitly outside Milestone 1.
- **FACT:** `core/auction_brain.py` is used by `core/live_capture.py`, but neither is in the current `app/main.py -> vision_capture_worker()` solve call chain. It must not be treated as the current EXE Solver owner.

### 2.4 Ownership answer

| Question | Answer |
|---|---|
| Where does the current final Solver run? | In the active Overlay's WebView2 JavaScript runtime. |
| Who invokes it? | `overlay_alpha.html:paintResult()`. |
| Input source? | Local manual UI facts or Canonical/Solver-input payload returned by parent Python. |
| Output destination? | A transient `engineResult`, then Overlay DOM; no shared result SOT is written. |
| Overlay owner or consumer? | **Owner/executor** for the current final Manual Alpha Solver; consumer of Python facts and optional sidecar inputs. |
| Node Shadow? | Production live-vision sidecar/evidence producer, not final Solver authority. |
| `solver_core_v06.js` production chain? | Yes, through `live_shadow_runtime.js` helper extraction; not through the active Overlay final solve. |

---

## 3. Two-WebView risk

- **FACT:** each WebView2 controller navigates its own document and has its own page globals, event handlers, timers, DOM, and WebSocket object. Sharing a browser environment/process does not turn two pages into one JavaScript heap.
- **FACT:** `overlay_alpha.html` creates mutable `manualState`, `syncTimer`, `solverTimer`, a WebSocket reconnect timer, and executes `AuctionEngineV06.solveAuctionPipeline()` (`core/overlay_alpha.html:570-604`, `core/overlay_alpha.html:903-927`, `core/overlay_alpha.html:1206-1234`).
- **INFERENCE:** if Main Window loads the same Alpha page or equivalent scripts, it creates a second manual-state buffer, second local Solver scheduling path, second WS connection/reconnect loop, and independently computed transient result. Even with identical inputs, edit timing, message ordering, page lifecycle, and local state can diverge.
- **RECOMMENDATION:** explicitly prohibit loading `auction_engine_v06.js` in the Milestone 1 Main Window. Loading the engine file in two WebViews is not Shared Core; it is two callable Solver runtimes. Do not create a second CurrentMatch or copy `LATEST_PAYLOAD` into a new mutable Main model either.

---

## 4. CurrentMatch / Canonical State data flow

### 4.1 Manual path — current active Alpha path

| Step | Owner | Structure | Transport | Mutability | SOT status |
|---|---|---|---|---|---|
| User edit | Overlay WebView | `manualState` + input DOM | in-page | mutable | edit buffer only |
| Fact submission | Overlay | `{action: "manual_facts", facts: patch}` | WebView2 `postMessage` | message copy | command only |
| Current match | Parent Python | module-level `CURRENT_MATCH: CurrentMatch` | native function call | mutable, one DRAFT | **manual fact SOT** |
| Snapshot | Parent Python | `CurrentMatch.snapshot()` / Canonical v7 dict | copied dict | immutable by convention only | point-in-time fact projection |
| Solver input | Parent Python | `canonical_to_v06_solver_input(canonical)` | payload/WS | copied dict | adapter projection, not SOT |
| Solver execution | Overlay WebView | `AuctionEngineV06.solveAuctionPipeline()` | in-page call | transient | current calculation authority |
| Result display | Overlay WebView | `engineResult` -> DOM | in-page | transient | no shared/persisted result SOT |
| Latest bus cache | Parent Python | `LATEST_PAYLOAD` | WS fan-out | mutable `dict.update` | convenience cache, **not canonical state** |

### 4.2 Vision path — separate owner today

| Step | Owner | Structure | Transport | Mutability | SOT status |
|---|---|---|---|---|---|
| Per-frame state | vision child process | `NTEVisionPipeline.current_context` | same-process calls | mutable across frames/match | live-vision working state |
| Shadow profile | vision child + Node | compact `probabilityProfile` | stdin/stdout JSON | cached/generation-guarded | sidecar evidence, not match identity SOT |
| HUD payload | vision child | dict from `build_in_auction_hud_payload()` | WS to parent bus | copied message | presentation payload |
| Parent cache/fanout | parent Python | `LATEST_PAYLOAD` | WS | mutable merge | not atomic/canonical |
| Current active Alpha consumption | Overlay | filters WS message | WS | N/A | raw vision payload currently ignored |

- **FACT:** manual `CURRENT_MATCH` and vision `pipeline.current_context` live in different processes and are not one shared object.
- **INFERENCE:** “Canonical State” in the current code means the manual Canonical v7 fact projection; it is not yet a universal manual+vision+result store. Describing `LATEST_PAYLOAD` as that universal SOT would be incorrect.
- **RECOMMENDATION for Milestone 1:** Main Window should read no Solver state because its only required behavior is Overlay visibility/lifetime control. If it needs a status indicator, read an immutable snapshot/status projection from the existing parent host; do not compute and do not become another mutable owner. A future result-sharing contract is a later milestone.

---

## 5. Main Window architecture candidates

| Candidate | M1 change size | Second Solver? | Solver-owner migration? | Overlay regression risk | Verdict |
|---|---:|---:|---:|---:|---|
| **A. Native WinForms Main + existing DComp Overlay; Solver stays Overlay** | Small | No, if Main does not load engine | No | Low/medium: lifecycle only | **SELECT** |
| B. Main becomes Solver owner; Overlay consumer | Large | Avoidable, but requires new IPC/result contract | Yes | High | Reject for M1 |
| C. Python/native Shared Core owns Solver; both WebViews consume | Very large | No after migration | Yes, plus JS/native boundary redesign | Very high | Reject for M1 |
| D. Hidden/dedicated Solver WebView/service consumed by both | Medium/large | One runtime, but new service and messaging | Yes | High | Reject for M1 |

**RECOMMENDATION:** select **A0** — a standard WinForms Main Window with native controls only for this slice, plus the existing DComp Overlay. If a WebView shell is introduced later for product UI, it must initially remain presentation-only and must not load the Solver engine.

Why this is the minimum:

1. It changes only application/window ownership, which is the milestone's purpose.
2. It leaves the active Solver call chain untouched.
3. It adds no second CurrentMatch, no second timers/WS runtime, and no output reconciliation problem.
4. It permits one EXE, one parent process, one STA UI thread, and two windows without claiming that the windows share JavaScript state.

---

## 6. Window lifecycle design

### 6.1 Recommended target lifecycle

```text
parent process start
  -> start daemon/support services as today
  -> start one STA UI thread
  -> create Main Window
  -> create existing Overlay helper window
  -> initialize Overlay WebView2 exactly once
  -> show Main Window
  -> Overlay visible/hidden by Main command
  -> Application.Run(mainWindow)

Main Window close
  -> enter idempotent shutdown guard
  -> stop accepting UI commands
  -> flush current manual draft
  -> request/stop vision child (and its Shadow/Node descendants)
  -> stop Overlay timers/callbacks
  -> close/dispose Overlay WebView controller and form
  -> stop WS loop or let a documented final process-exit boundary end it
  -> dispose Main Window
  -> Application.Run(mainWindow) returns
  -> STA thread returns
  -> Python main-thread Join returns
  -> process exits normally
```

- **RECOMMENDATION:** `Application.Run(mainWindow)` should own the application lifetime.
- **RECOMMENDATION:** Overlay close/hide must not exit the app. The Main Window's toggle should call the existing Overlay form's `Show()`/`Hide()` on the same STA thread. Hiding must not recreate the Overlay, WebView, Solver runtime, or WebSocket.
- **RECOMMENDATION:** Main close must close/dispose Overlay and child services once, then allow normal process return. Replace the `os._exit(0)` application-level exit behavior for this path with the centralized shutdown sequence; otherwise “clean shutdown” remains untrue.
- **RECOMMENDATION:** logical lifetime ownership and native Win32 window ownership must remain distinct. The Overlay currently sets its native owner HWND to the game to preserve topmost behavior (`app/DirectCompositionHost.cs:259-290`). Do not make Main Window its Win32 owner while that game-owner behavior is active; Main is the application-lifetime owner, Overlay remains a game-attached helper at the native window layer.

---

## 7. CoreWebView2Environment

- **FACT:** current code creates one `CoreWebView2Environment` with user data folder `%TEMP%/nte_webview2_data`, then passes it to `DirectCompositionHudForm.InitializeComposition()` (`app/main.py:1502-1556`).
- **FACT:** `InitializeComposition()` creates a composition controller and obtains that controller's `CoreWebView2` (`app/DirectCompositionHost.cs:316-405`).
- **FACT:** Microsoft describes `CoreWebView2Environment` as a grouping for controls that can share browser process/user-data-folder resources; safe shutdown is at the controller level. See [Main classes for WebView2](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/environment-controller-core), [Process model](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/process-model), and [User data folders](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/user-data-folder).
- **INFERENCE:** if a later Main Window really needs WebView2, creating both controllers from the same environment on the same STA UI host is a reasonable resource/lifecycle choice.
- **RECOMMENDATION:** phrase the boundary precisely: **shared Environment/profile/process resources are not a shared JS runtime, shared DOM, shared timers, shared CurrentMatch, or shared Solver state.** Each controller/page still needs an explicit data contract.
- **RECOMMENDATION for M1:** since the Main Window does not need WebView2, create no second controller yet. Keep the environment scoped to the application host rather than buried as an Overlay-local temporary only if that makes orderly lifetime management clearer.

---

## 8. First implementation boundary (do not implement in this audit)

### Required files/changes

1. **New `app/main_window.py` (recommended):** one small native WinForms `MainWindow` class with an Overlay visibility toggle and close event. No WebView2 and no Solver imports.
2. **Modify `app/main.py`:** replace Overlay-owned `Application.Run(form)` with a small application host on the existing STA thread that creates Main + Overlay, routes show/hide, and centralizes idempotent shutdown. Preserve the existing Overlay construction, WebMessage bridge, environment, HTML, and Solver runtime.
3. **Modify `app/异环拍卖助手.spec`:** include the new module as needed and correct the active runtime assets (`overlay_alpha.html`, `v06_adapter.js`; retain `auction_engine_v06.js`). Do not rely on stale build output.
4. **New focused lifecycle tests:** verify startup shows Main, hide/show preserves the same Overlay/form/WebView instance, Overlay hide/close does not end app lifetime, Main close invokes shutdown once, and no Main asset imports/loads Solver JS.
5. **Only if required for clean disposal:** minimally extend `app/DirectCompositionHost.cs` and rebuild its checked-in DLL to expose an idempotent Overlay resource-close method. Do not alter rendering, topmost, drag, Solver, or WebView message behavior.

### Explicit non-changes

- Do not load `auction_engine_v06.js`, `solver_core_v06.js`, `v06_adapter.js`, or `overlay_alpha.html` in Main Window.
- Do not create a second `CurrentMatch`.
- Do not move Solver ownership.
- Do not reconnect or redesign live vision.
- Do not introduce History UI, OCR changes, AI, algorithm changes, or visual redesign.

### One-action next cut

**RECOMMENDATION:** implement the native `MainWindow` plus the single-STA application host/lifetime inversion in one guarded vertical slice: instantiate the existing Overlay once, run `Application.Run(mainWindow)`, and make one button call `Show()`/`Hide()` on that exact Overlay instance. Include the idempotent Main-close shutdown hook in the same slice because lifetime ownership is otherwise incomplete.

---

## 9. Risks and gates

### Maximum regression risk

**INFERENCE:** the largest runtime regression risk is not the Main form itself; it is changing the message-loop/lifetime owner while the existing Overlay still has WinForms timers, a game-owner HWND, WebView callbacks, WS reconnect behavior, and a vision child. Incorrect shutdown ordering can invoke callbacks on a hidden/disposed Overlay, leave the Node/vision subtree alive, lose a pending draft, or terminate via `os._exit(0)` before cleanup.

### Required implementation gates

- The active Overlay is created exactly once per app session.
- Hiding/showing preserves the same WebView and JS runtime.
- Main contains no Solver script/import/call site.
- `CURRENT_MATCH` remains the sole parent-process manual fact owner.
- `Application.Run()` receives Main Window, not Overlay.
- Main close reaches one idempotent cleanup path; double FormClosing/exit commands are harmless.
- Overlay's native game-owner/topmost behavior still works when visible.
- Fresh packaged EXE contains the actually loaded HTML and JS adapter.
- Existing Overlay/manual Solver tests and a packaged startup smoke test pass.

---

## 10. Final audit answers

1. **Current real EXE lifecycle:** parent starts icon/WS daemon threads, creates one STA GUI thread, creates Overlay + its WebView, and runs `Application.Run(overlayForm)` while the Python main thread joins; HUD-ready starts a separate vision-worker EXE, which can spawn a Node Shadow child. Overlay close currently ends the message loop and thus the app.
2. **Current actual final Solver owner:** the active `overlay_alpha.html` WebView runtime via `paintResult() -> AuctionEngineV06.solveAuctionPipeline()`. Node Shadow separately computes an evidence/profile sidecar.
3. **Overlay owner or consumer:** final Manual Alpha Solver owner/executor; consumer of Python-owned facts. It is not a passive display.
4. **CurrentMatch/Canonical flow:** Overlay edit buffer -> WebMessage -> parent `CURRENT_MATCH` manual fact SOT -> Canonical v7 snapshot -> v0.6 Solver-input projection -> Overlay -> JS Solver -> transient DOM result. Vision has a separate child-process `current_context`; `LATEST_PAYLOAD` is only a mutable bus cache.
5. **Should Main load Solver JS?** **No. Do not load it in Milestone 1.**
6. **Milestone 1 architecture:** candidate A0 — native WinForms Main, existing DirectComposition Overlay helper, current Solver owner unchanged, no Main WebView required.
7. **Who owns `Application.Run(...)`?** Main Window: `Application.Run(mainWindow)`.
8. **Minimum files:** new `app/main_window.py`; modify `app/main.py`; correct `app/异环拍卖助手.spec`; add focused lifecycle/package tests; touch `DirectCompositionHost.cs`/DLL only if explicit resource close cannot be achieved safely from the host.
9. **Maximum regression risk:** shutdown/message-loop inversion racing the Overlay's WebView callbacks, timers, game HWND ownership, WS reconnect, vision/Node child, and current hard-exit path.
10. **If the next cut allows one action:** build the native Main/lifetime-owner vertical slice around the one existing Overlay instance, including show/hide and idempotent Main-close cleanup—without loading or moving Solver code.
