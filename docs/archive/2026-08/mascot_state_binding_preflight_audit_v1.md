# Mascot State Binding Preflight Audit v1

## Scope

This is a read-only audit of existing runtime signals that could drive the Main Window mascot without granting Main new business authority, exposing mutable `CurrentMatch`, or connecting Main to the Solver.

Audit target: current HEAD `5b1fa7971a3a457bb9c2db3ed64aec306278b6be`.

Verdict: **PARTIAL_BINDING_SAFE**.

- **FACT:** `idle` and the shutdown-only use of `sleep` can be driven from the current Main bridge today.
- **FACT:** real `loading` and `thinking` signals already exist in the application transport layer, but they are not exposed to Main.
- **FACT:** no reliable read-only `result-ready` signal currently crosses from the Overlay Solver runtime back to native/Main.
- **RECOMMENDATION:** reuse the existing `request_app_status` action and enrich only its response with a whitelisted immutable presentation snapshot. Do not add a Solver API, expose raw `LATEST_PAYLOAD`, or read `CurrentMatch`.

## 1. Current Main bridge

### FACT

`MainWindowBridge` is deliberately narrow (`app/main_window.py:207-239`). Its allowed actions are:

- `toggle_overlay`
- `get_overlay_visibility`
- `request_app_status`

Only `toggle_overlay` mutates anything, and that mutation is limited to Overlay visibility. Both read actions currently return the same status fields:

- `overlayVisible`
- `applicationState: "ready"`
- `presentationData: "mock"`
- `solverOwner: "overlay_runtime"`

The native host also pushes the same `app_status` message type on navigation completion, Overlay visibility changes, and shutdown (`app/main_window.py:363-390`, `429-439`). `begin_shutdown()` first stops accepting commands and then pushes `applicationState: "shutting_down"`.

The Main page consumes `mascotPresentation`, `overlayVisible`, and `applicationState` (`core/main_window.js:178-192`). Mascot state changes remain local presentation controls (`core/main_window.js:47-93`, `201-203`). There is no `set_mascot_state` native action and no Main Solver call.

### INFERENCE

The bridge's **permission surface is already sufficient** for a read-only mascot binding. The missing part is status payload content, not a new command.

`request_app_status` is defined but the current page startup requests only `get_overlay_visibility` (`core/main_window.js:209-212`). A future binding may call the existing read action or receive an existing `app_status` push; it does not need another privileged action.

## 2. Existing runtime signals

| Signal | Existing owner/source | What it actually proves | Currently exposed to Main | Safe mascot use |
|---|---|---|---|---|
| `applicationState: ready` | Native Main host | Main presentation and native bridge are operating | Yes | Fallback `idle` |
| `applicationState: shutting_down` | Native shutdown coordinator/Main host | Application cleanup has started and UI commands are disabled | Yes, push | Transient `sleep` |
| `overlayVisible` | `OverlayVisibilityController` / native Overlay instance | Same Overlay instance is shown or hidden | Yes | Status decoration only; do not drive mascot |
| Vision subprocess `poll()` | `VISION_PROCESS` in `app/main.py:1350-1387` | Process is absent, alive, or exited | No | Health metadata only; alive is not ready/processing |
| `refreshPending: true` | `request_force_refresh()` (`app/main.py:229-260`) | A specific refresh transaction has been requested and not yet committed | No | `loading`, if request correlation/staleness is preserved |
| `refreshPending: false` | Vision worker refresh commit (`app/main.py:987-1039`) | The refresh transaction completed or failed to acquire a frame | No | End `loading`; not automatically `success` |
| `isLoading` / `scene: AUCTION_LOADING` / `solverStatus: loading` | Navigation HUD payload (`app/main.py:749-779`) | The captured game scene is in a loading transition | No | `loading` |
| `shadowUpdating: true` | `live_shadow.attach_live_shadow()` and in-auction HUD payload (`core/live_shadow.py:519-529`, `app/main.py:674-735`) | A probability-profile shadow computation is in flight | No | `thinking` |
| `solverStatus: valid` | In-auction payload builder (`app/main.py:656-681`) | Input context has a positive round number | No | **Not** `success`; this precedes Overlay solving |
| `solverStatus: incomplete` | In-auction payload builder | Input context is incomplete | No | Do not auto-warning; remain `idle`/current state |
| lobby/navigation/standby scene | Navigation HUD payload (`app/main.py:780-841`) | No explicit foreground processing is active | No | `idle` |
| `gameDetected: false` | Vision no-frame/standby payload | No usable game frame was detected | No | Normally `idle`, not automatically warning |
| `isSettlement` | In-auction payload | Settlement scene was observed | No | Scene only; not result-ready |
| `settlementReady` | Vision pipeline internal context | Settlement evidence met its internal finalization gate | Not included in the Main/Overlay HUD status subset | Keep unbound in v1 |
| Overlay Solver result | `overlay_alpha.html::paintResult()` calls `AuctionEngineV06.solveAuctionPipeline()` (`core/overlay_alpha.html:961-1005`) | A result was computed inside the Overlay JS runtime | No return/ack to native or Main | `success` unavailable as a real automatic state |

## 3. Vision worker status

### FACT

`start_vision_worker()` stores only a `subprocess.Popen` handle. `stop_vision_worker()` terminates or kills that process (`app/main.py:1350-1421`). There is no explicit warm-up state, heartbeat, ready acknowledgment, current-frame activity flag, or health enum.

The worker can be disabled by `NTE_DISABLE_VISION=1`, fail to spawn, be alive, or have exited. The process also contains broad exception containment, so process liveness alone does not establish OCR readiness, WebSocket connectivity, successful capture, or current processing.

### INFERENCE

It is safe to expose a read-only process-liveness classification, but unsafe to translate `process alive` into `loading`, `thinking`, or `success`.

### RECOMMENDATION

If exposed later, use a deliberately limited field such as:

```json
{
  "visionProcessState": "running | stopped | exited | disabled"
}
```

Do not call this field `ready`. Do not auto-map `exited` to `warning` until the host can distinguish an unexpected exit from intentional stop/disable during shutdown.

## 4. Processing, waiting, and result-ready

### Real processing/waiting signals

- **FACT:** `refreshPending: true` is a real transaction-pending signal and is suitable for `loading`.
- **FACT:** `AUCTION_LOADING`/`isLoading` is a real captured scene transition and is suitable for `loading`.
- **FACT:** `shadowUpdating: true` is a real in-flight computation marker and is suitable for `thinking`.
- **FACT:** normal lobby, navigation, standby, or auction payloads with no higher-priority pending flag are suitable for fallback `idle`.

### Missing result-ready signal

- **FACT:** the Overlay receives data over WebSocket and runs `solveAuctionPipeline()` locally in `paintResult()`.
- **FACT:** it does not send a sanitized `result-ready` acknowledgment to native/Main after rendering.
- **INFERENCE:** `solverStatus: valid` cannot be used as `success`; it describes input readiness before the Overlay Solver result exists.
- **INFERENCE:** `shadowUpdating: false` cannot be used as `success`; it may mean cached, skipped, insufficient input, no snapshot, or finished.
- **RECOMMENDATION:** keep `success` manual/local. If product binding later truly requires automatic success, the smallest reliable addition is a presentation-only Overlay acknowledgment containing no result values, Solver API, canonical facts, or mutable objects. That is outside this audit and should be a separate reviewed change.

### Warning signal

- **FACT:** no standardized, correlated warning signal currently reaches Main.
- **INFERENCE:** no game frame, incomplete input, or hidden Overlay can all be normal user states; mapping them directly to `warning` would create false alarms.
- **RECOMMENDATION:** keep `warning` manual/local. A future warning binding should use explicit whitelisted attention codes (for example, a correlated user refresh ending in `no_frame`) rather than raw error strings or broad heuristics.

### Sleep signal

- **FACT:** there is no inactivity timer, system-lock signal, semantic idle duration, or reliable "nothing to do" business signal.
- **INFERENCE:** Overlay hidden is a user display preference, not proof that the app or mascot should sleep.
- **RECOMMENDATION:** allow only `applicationState: shutting_down -> sleep` automatically in v1. Keep all other `sleep` changes manual/local.

## 5. Safe state mapping

The following mapping is ordered from highest to lowest priority:

| Mascot state | Safe real trigger | Availability now | Decision |
|---|---|---|---|
| `sleep` | `applicationState == "shutting_down"` | Already in Main bridge | Auto-bind only for shutdown |
| `loading` | `refreshPending == true` | Exists, not exposed to Main | Bind after sanitized status increment |
| `loading` | `isLoading == true` or scene class is `loading` | Exists, not exposed to Main | Bind after sanitized status increment |
| `thinking` | `shadowUpdating == true` | Exists, not exposed to Main | Bind after sanitized status increment |
| `idle` | app ready with no higher-priority signal; lobby/navigation/standby | Ready exists; scene class not exposed | Safe fallback now; richer fallback after increment |
| `success` | None reliable | Not available | Manual/local only |
| `warning` | None reliable | Not available | Manual/local only |
| `sleep` | Non-shutdown idle/sleep semantics | Not available | Manual/local only |

Overlay visibility remains orthogonal and must not override this priority chain.

## 6. Why raw `LATEST_PAYLOAD` is not a safe bridge

### FACT

`LATEST_PAYLOAD` is updated by merging dictionaries from multiple origins (`app/main.py:251`, `361`, `571`, `580`). Those origins include Vision worker payloads and manual payloads. Manual payloads can contain canonical/solver input derived from `CurrentMatch`.

Merging partial payloads also permits unrelated fields from an older message to remain in the cache. For example, a pending refresh and its completion must be correlated by `refreshRequestId`; `solverStatus: refreshing` alone remains ambiguous after a no-frame completion (`app/main.py:999-1012`).

### RECOMMENDATION

Never return `LATEST_PAYLOAD` itself to Main and never let Main JS select fields from it. Introduce a native-side whitelist that copies only presentation-safe primitives into an immutable snapshot and preserves transaction correlation.

The snapshot must exclude at least:

- `canonical`
- `solverInput`
- `CurrentMatch` or any reference to it
- item/auction facts and bids
- OCR text/results
- settlement data
- Solver results/decisions
- mutable dictionaries owned by another runtime

## 7. Minimal read-only bridge increment

### RECOMMENDATION

Keep all three existing actions unchanged. Extend only `request_app_status` and existing `app_status` pushes with a sanitized object such as:

```json
{
  "presentationRuntime": {
    "snapshotVersion": 1,
    "visionProcessState": "running",
    "refreshPending": false,
    "sceneClass": "auction | loading | lobby | navigation | unknown",
    "shadowUpdating": false
  }
}
```

Owner boundaries:

1. The Python/native host owns construction of this immutable presentation snapshot.
2. Vision/transport messages may update only whitelisted scalar fields; they do not become Main authority.
3. Main reads the snapshot and selects a mascot asset locally.
4. Main cannot write any runtime state through this object.
5. Overlay remains the only Solver runtime and sends no Solver object to Main.

For the first implementation, a status provider read by the existing `request_app_status` action is the smallest permission-preserving path. If status changes are later pushed, they should reuse `app_status` and marshal to the Main GUI thread; they must not expose the live WebSocket payload object.

### INFERENCE

This is a payload enrichment, not a new Main capability. It preserves the current bridge authority while enabling `loading` and `thinking` from real read-only signals.

It still does not create a reliable `success` or `warning` signal. Those states must remain manual/local until independently specified evidence exists.

## 8. Final answers

1. **Real states safely mappable now:** `ready -> idle`; `shutting_down -> sleep`. Overlay visibility stays a separate status.
2. **Real states safely mappable after a minimal read-only status enrichment:** refresh pending or game loading -> `loading`; shadow computation in flight -> `thinking`; ordinary scenes -> `idle`.
3. **States without reliable signals:** `success`, `warning`, and normal-operation `sleep`; they must remain manual/local.
4. **Vision worker:** only process liveness exists. It is not a readiness or processing signal and should not directly drive the mascot.
5. **Bridge reuse:** the current action surface can be reused completely. The current response payload is insufficient.
6. **Minimal increment:** enrich `request_app_status`/`app_status` with a native-owned, immutable, whitelisted presentation runtime snapshot. Add no action and expose no mutable object.
7. **Solver/CurrentMatch boundary:** Main must not read Solver output, raw `LATEST_PAYLOAD`, canonical facts, or `CurrentMatch`. Overlay remains the sole Solver owner.

No implementation was performed in this audit.
