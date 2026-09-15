/**
 * Live Historical Shadow WebView Adapter (v1).
 *
 * Runs inside the existing Overlay WebView2 / Chromium V8 context.
 * Performs live shadow probability profile computation without external Node subprocess.
 * Reuses existing AuctionEngineV06, ShadowProfileV06, and frozen Solver functions.
 */
(function (global) {
  "use strict";

  const EXPECTED_SOLVER_CORE_SHA256 = "1ec8dca270a8219eb00133421723a114f3649b81cd07c769c765ac2c7afed07f";
  const EXPECTED_SOLVER_CORE_LF_SHA256 = "547c89e2751f7c6d9d2732da6bd8e1e6ebaa9f6daa873a4699044df16f951156";

  let cachedRecords = [];
  let solverInitialized = false;
  let initError = null;

  function initSolver(solverCode, expectedSha256) {
    if (solverInitialized) {
      return { ok: true, alreadyInitialized: true };
    }
    try {
      const code = String(solverCode || "");
      if (!code) {
        throw new Error("EMPTY_SOLVER_CODE");
      }
      const targetHash = expectedSha256 || EXPECTED_SOLVER_CORE_SHA256;
      if (global.AuctionEngineV06 && typeof global.AuctionEngineV06.sha256Hex === "function") {
        const actualHash = global.AuctionEngineV06.sha256Hex(code);
        const actualLfHash = global.AuctionEngineV06.sha256Hex(code.replace(/\r\n/g, "\n"));
        const matchesTarget = (actualHash === targetHash) || (actualLfHash === targetHash);
        const matchesKnown = (actualHash === EXPECTED_SOLVER_CORE_SHA256) || (actualHash === EXPECTED_SOLVER_CORE_LF_SHA256) || (actualLfHash === EXPECTED_SOLVER_CORE_LF_SHA256);
        if (!matchesTarget && !matchesKnown) {
          throw new Error("SHADOW_RUNTIME_SOURCE_MISMATCH: expected=" + targetHash + " actual=" + actualHash);
        }
      }

      // Check if functions are already available on window/global
      if (
        typeof global.expandStatesForValuation === "function" &&
        typeof global.stateComponents === "function" &&
        typeof global.candidateStateWeight === "function"
      ) {
        solverInitialized = true;
        return { ok: true, reusedExisting: true };
      }

      // Perform frozen deterministic expose replacements (identical to live_shadow_runtime.js)
      let transformed = code
        .replace("let state = loadState();", "let state = loadState(); window.state = state;")
        .replace(
          "function redProbabilityProfile(ctx,states=[],componentRows=[]){",
          "window.redProbabilityProfile=function redProbabilityProfile(ctx,states=[],componentRows=[]){"
        )
        .replace(
          "function stateComponents(ctx,state){",
          "window.stateComponents=function stateComponents(ctx,state){"
        )
        .replace(
          "function candidateStateWeight(state,ctx={}){",
          "window.candidateStateWeight=function candidateStateWeight(state,ctx={}){",
        )
        .replace(
          "function expandStatesForValuation(ctx, states){",
          "window.expandStatesForValuation=function expandStatesForValuation(ctx, states){"
        );

      const origGetElementById = (typeof document !== "undefined" && document.getElementById) ? document.getElementById.bind(document) : null;
      const origQuerySelector = (typeof document !== "undefined" && document.querySelector) ? document.querySelector.bind(document) : null;
      const dummyEl = {
        value: "",
        options: [],
        children: [],
        dataset: {},
        style: {},
        classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
        addEventListener() {},
        removeEventListener() {},
        appendChild() {},
        closest() { return null; },
        reset() {},
        focus() {}
      };

      if (origGetElementById) {
        document.getElementById = function (id) {
          const el = origGetElementById(id);
          return el !== null ? el : dummyEl;
        };
      }
      if (origQuerySelector) {
        document.querySelector = function (sel) {
          const el = origQuerySelector(sel);
          return el !== null ? el : dummyEl;
        };
      }

      const mute = ["log", "info", "warn"];
      const saved = {};
      mute.forEach((k) => {
        saved[k] = console[k];
        console[k] = () => {};
      });

      try {
        const fn = new Function(transformed);
        fn.call(global);
      } finally {
        if (origGetElementById) {
          document.getElementById = origGetElementById;
        }
        if (origQuerySelector) {
          document.querySelector = origQuerySelector;
        }
        mute.forEach((k) => {
          console[k] = saved[k];
        });
      }

      if (
        typeof global.expandStatesForValuation !== "function" ||
        typeof global.stateComponents !== "function" ||
        typeof global.candidateStateWeight !== "function"
      ) {
        throw new Error("SOLVER_FUNCTIONS_EXPOSE_FAILED");
      }

      solverInitialized = true;
      initError = null;
      return { ok: true, initialized: true };
    } catch (err) {
      initError = String((err && err.message) || err);
      return { ok: false, error: initError };
    }
  }

  function compactProfile(profile, extra) {
    const states = (profile.stateCandidates || []).map((s) => ({
      g: s.g,
      p: s.p,
      r: s.r,
      weight: s.weight,
      relativeWeight: s.relativeWeight,
      supported: Boolean(s.shadow && Number.isFinite(Number(s.shadow.p50))),
      redMode: s.redMode || null,
      shadow: s.shadow
        ? {
            p20: s.shadow.p20,
            p50: s.shadow.p50,
            p80: s.shadow.p80,
          }
        : null,
    }));
    return {
      supportedStateCount: profile.supportedStateCount,
      totalStateCount: profile.totalStateCount,
      supportedWeight: profile.supportedWeight,
      totalWeight: profile.totalWeight,
      coverageRatio: profile.coverageRatio,
      isFullShadow: Boolean(profile.shadowCoverage && profile.shadowCoverage.isFull),
      shadowWhole: profile.shadowWhole
        ? {
            p20: profile.shadowWhole.p20,
            p50: profile.shadowWhole.p50,
            p80: profile.shadowWhole.p80,
          }
        : null,
      partialShadowP20: profile.partialShadowP20 ?? null,
      partialShadowP50: profile.partialShadowP50 ?? null,
      partialShadowP80: profile.partialShadowP80 ?? null,
      stateCandidates: states,
      source: profile.source || null,
      status: profile.status || null,
      expandedStates: extra.expandedStates,
      exactStates: extra.exactStates,
    };
  }

  function normalizeCtx(raw) {
    const ctx = Object.assign({}, raw || {});
    if (ctx.avg == null && ctx.goldAvg != null) ctx.avg = ctx.goldAvg;
    if (ctx.purple == null && ctx.purpleCount != null) ctx.purple = ctx.purpleCount;
    ctx.publicInfo = ctx.publicInfo && typeof ctx.publicInfo === "object" ? ctx.publicInfo : {};
    ctx.roundingMode = ctx.roundingMode || "floor";
    if (!ctx.costs && ctx.lobbyEntryCost != null) {
      ctx.costs = { entry: Number(ctx.lobbyEntryCost), info: 0, other: 0 };
    }
    return global.AuctionEngineV06.normalizeKnownContext(ctx);
  }

  function buildSupportCaptureEnvelope(profile, expandedStates, predictionSnapshot, ctx) {
    if (!predictionSnapshot || !profile) return null;
    const eng = global.AuctionEngineV06;
    return {
      schemaVersion: "production-support-envelope.v1",
      capturePhase: "PREDICTION_COMPLETED_PRE_SETTLEMENT",
      capturedAt: new Date().toISOString(),
      predictionSnapshot,
      predictionSnapshotSha256: eng && typeof eng.sha256Json === "function" ? eng.sha256Json(predictionSnapshot) : null,
      runtimeMatchId: String((ctx && (ctx.matchId || ctx.id)) || "").trim() || null,
      collectionClass: String((ctx && ctx.collectionClass) || "").trim() || null,
      fullCandidateStates: (expandedStates || []).map((s) => ({
        g: s.g,
        p: s.p,
        r: s.r,
      })),
      valuationStates: profile.stateCandidates || [],
      aggregateDistribution: profile.shadowWhole || null,
      tailEvidence: {
        source: profile.source || null,
        status: profile.status || null,
        currentDistribution: profile.currentDistribution || null,
        stateDistributions: profile.stateDistributions || [],
        historyEvidence: profile.historyEvidence || [],
      },
    };
  }

  function compute(req) {
    const startTime = performance.now();
    const eng = global.AuctionEngineV06;
    const sh = global.ShadowProfileV06;
    if (!eng || !sh) {
      return { ok: false, error: "ENGINE_OR_SHADOW_NOT_LOADED" };
    }
    if (
      typeof global.expandStatesForValuation !== "function" ||
      typeof global.stateComponents !== "function" ||
      typeof global.candidateStateWeight !== "function"
    ) {
      return { ok: false, error: "SOLVER_FUNCTIONS_NOT_INITIALIZED: " + String(initError || "uninitialized") };
    }
    if (global.LiveShadowCompute && typeof global.LiveShadowCompute.compute === "function") {
      const sharedResult = global.LiveShadowCompute.compute(
        req,
        cachedRecords,
        global,
        eng,
        sh,
        "live_shadow_webview_adapter"
      );
      sharedResult.durationMs = performance.now() - startTime;
      return sharedResult;
    }

    const ctx = normalizeCtx(req.ctx || req);
    const q = Number(ctx.q);
    const avg = Number(ctx.avg);
    if (!Number.isFinite(q) || q <= 0 || !Number.isFinite(avg) || avg <= 0) {
      return {
        ok: true,
        insufficient: true,
        exactStates: [],
        expandedStates: [],
        probabilityProfile: null,
        predictionSnapshot: null,
        frozenPrediction: null,
        supportCaptureEnvelope: null,
        durationMs: performance.now() - startTime,
      };
    }

    const recs = Array.isArray(req.records) ? req.records : cachedRecords;
    if (global.state) global.state.records = recs;

    const exactRaw = eng.solveExactStatesSync({
      q,
      avg,
      p: ctx.purple,
      purple: ctx.purple,
      goldCount: ctx.goldCount,
      redCount: ctx.redCount,
      knownGold: ctx.knownGoldRaw,
      knownPurple: ctx.knownPurpleRaw,
      knownRed: ctx.knownRedRaw,
      knownGoldGroups: ctx.knownGoldGroups,
      knownPurpleGroups: ctx.knownPurpleGroups,
      knownRedGroups: ctx.knownRedGroups,
      fieldCondition: ctx.fieldCondition,
      playedAt: ctx.playedAt,
      totalGrids: ctx.totalGrids,
      roundingMode: ctx.roundingMode,
    });
    const exactStates = (exactRaw.states || []).map((s) => ({
      g: s.G ?? s.g,
      p: s.P ?? s.p,
      r: s.R ?? s.r,
      G: s.G ?? s.g,
      P: s.P ?? s.p,
      R: s.R ?? s.r,
      gold: { unconstrained: true, matches: [] },
      purple: { unconstrained: true, matches: [] },
    }));
    const expanded = global.expandStatesForValuation(ctx, exactStates);
    const componentRows = expanded
      .map((state) => {
        const component = global.stateComponents(ctx, state);
        return component
          ? {
              state,
              component,
              weight: global.candidateStateWeight(state, ctx),
            }
          : null;
      })
      .filter(Boolean);
    const profile = sh.buildProbabilityProfile(ctx, expanded, {
      records: recs,
      componentRows,
      stateComponentsFn: global.stateComponents,
    });
    const compact_profile = compactProfile(profile, {
      exactStates: exactStates.map((s) => ({ G: s.g, P: s.p, R: s.r })),
      expandedStates: expanded.map((s) => ({ G: s.g, P: s.p, R: s.r })),
    });

    const datasetRevision = req.datasetRevision || ctx.datasetRevision || null;
    const codeRevision = req.codeRevision || ctx.codeRevision || null;
    const pipelineResult = eng.solveAuctionPipeline(
      Object.assign({}, ctx, { probabilityProfile: compact_profile }),
      recs,
      { datasetRevision, codeRevision, runtime: "live_shadow_webview_adapter" }
    );
    const supportCaptureEnvelope = buildSupportCaptureEnvelope(
      profile,
      expanded,
      pipelineResult.predictionSnapshot || null,
      req.captureContext || null
    );

    const durationMs = performance.now() - startTime;

    return {
      ok: true,
      insufficient: false,
      exactStates: exactStates.map((s) => ({ G: s.g, P: s.p, R: s.r })),
      expandedStates: expanded.map((s) => ({ G: s.g, P: s.p, R: s.r })),
      probabilityProfile: compact_profile,
      predictionSnapshot: pipelineResult.predictionSnapshot || null,
      frozenPrediction: pipelineResult.frozenPrediction || null,
      supportCaptureEnvelope,
      durationMs,
    };
  }

  const api = {
    EXPECTED_SOLVER_CORE_SHA256,
    isReady() {
      return (
        Boolean(global.AuctionEngineV06) &&
        Boolean(global.ShadowProfileV06) &&
        typeof global.expandStatesForValuation === "function" &&
        typeof global.stateComponents === "function" &&
        typeof global.candidateStateWeight === "function"
      );
    },
    initSolver,
    setRecords(records) {
      cachedRecords = Array.isArray(records) ? records : [];
      return { ok: true, updated: true, nRecords: cachedRecords.length };
    },
    compute(req) {
      try {
        return compute(req);
      } catch (err) {
        return { ok: false, error: String((err && err.message) || err) };
      }
    },
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  global.LiveShadowWebviewAdapter = api;
})(typeof window !== "undefined" ? window : globalThis);
