/**
 * Shared live-shadow compute. Node runtime and Overlay adapter must call this
 * one function. HUD/Main only project the returned snapshot.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(
      require("./auction_engine_v06.js"),
      require("./shadow_profile_v06.js")
    );
  } else {
    root.LiveShadowCompute = factory(root.AuctionEngineV06, root.ShadowProfileV06);
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function (engine, shared) {
  "use strict";

  function compactProfile(profile, extra) {
    const states = (profile.stateCandidates || []).map((s) => ({
      g: s.g,
      p: s.p,
      r: s.r,
      weight: s.weight,
      relativeWeight: s.relativeWeight,
      supported: Boolean(s.shadow && Number.isFinite(Number(s.shadow.p50))),
      redMode: s.redMode || null,
      shadow: s.shadow ? { p20: s.shadow.p20, p50: s.shadow.p50, p80: s.shadow.p80 } : null
    }));
    return {
      supportedStateCount: profile.supportedStateCount,
      totalStateCount: profile.totalStateCount,
      supportedWeight: profile.supportedWeight,
      totalWeight: profile.totalWeight,
      coverageRatio: profile.coverageRatio,
      isFullShadow: Boolean(profile.shadowCoverage && profile.shadowCoverage.isFull),
      shadowWhole: profile.shadowWhole ? {
        p20: profile.shadowWhole.p20,
        p50: profile.shadowWhole.p50,
        p80: profile.shadowWhole.p80
      } : null,
      partialShadowP20: profile.partialShadowP20 ?? null,
      partialShadowP50: profile.partialShadowP50 ?? null,
      partialShadowP80: profile.partialShadowP80 ?? null,
      stateCandidates: states,
      source: profile.source || null,
      status: profile.status || null,
      expandedStates: extra.expandedStates,
      exactStates: extra.exactStates
    };
  }

  function normalizeCtx(raw) {
    const ctx = Object.assign({}, raw || {});
    if (ctx.avg == null && ctx.goldAvg != null) ctx.avg = ctx.goldAvg;
    if (ctx.purple == null && ctx.purpleCount != null) ctx.purple = ctx.purpleCount;
    ctx.publicInfo = ctx.publicInfo && typeof ctx.publicInfo === "object" ? ctx.publicInfo : {};
    ctx.roundingMode = ctx.roundingMode || "floor";
    return engine.normalizeKnownContext(ctx);
  }

  function buildSupportCaptureEnvelope(profile, expandedStates, predictionSnapshot, ctx) {
    if (!predictionSnapshot || !profile) return null;
    return {
      schemaVersion: "production-support-envelope.v1",
      capturePhase: "PREDICTION_COMPLETED_PRE_SETTLEMENT",
      capturedAt: new Date().toISOString(),
      predictionSnapshot,
      predictionSnapshotSha256: engine.sha256Json(predictionSnapshot),
      runtimeMatchId: String((ctx && (ctx.matchId || ctx.id)) || "").trim() || null,
      collectionClass: String((ctx && ctx.collectionClass) || "").trim() || null,
      fullCandidateStates: (expandedStates || []).map((s) => ({
        g: s.g,
        p: s.p,
        r: s.r
      })),
      valuationStates: profile.stateCandidates || [],
      aggregateDistribution: profile.shadowWhole || null,
      tailEvidence: {
        source: profile.source || null,
        status: profile.status || null,
        currentDistribution: profile.currentDistribution || null,
        stateDistributions: profile.stateDistributions || [],
        historyEvidence: profile.historyEvidence || []
      }
    };
  }

  function compute(req, records, host, eng, sh, runtimeName) {
    const usedEngine = eng || engine;
    const usedShared = sh || shared;
    const ctx = normalizeCtx(req.ctx || req);
    if (usedEngine.normalizeFieldCondition(ctx.fieldCondition).sparkleEvidenceOnly) {
      const limited = usedEngine.solveAuctionPipeline(ctx, [], {
        datasetRevision: req.datasetRevision || ctx.datasetRevision || null,
        codeRevision: req.codeRevision || ctx.codeRevision || null,
        runtime: runtimeName || "live_shadow_compute"
      });
      return {ok:true, insufficient:true, exactStates:[], expandedStates:[], probabilityProfile:null,
        predictionSnapshot:limited.predictionSnapshot, frozenPrediction:limited.frozenPrediction,
        supportCaptureEnvelope:null, computeHost:runtimeName || "live_shadow_compute"};
    }
    const q = Number(ctx.q);
    const avg = Number(ctx.avg);
    if (!Number.isFinite(q) || q <= 0 || !Number.isFinite(avg) || avg <= 0) {
      return {
        ok: true,
        insufficient: true,
        exactStates: [],
        expandedStates: [],
        probabilityProfile: null,
        computeHost: runtimeName || "live_shadow_compute"
      };
    }
    const recs = Array.isArray(req.records) ? req.records : records;
    const g = host || (typeof globalThis !== "undefined" ? globalThis : {});
    if (g.state) g.state.records = recs;

    const exactRaw = usedEngine.solveExactStatesSync({
      ...ctx,
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
      goldGrid: ctx.publicInfo?.goldGrid ?? ctx.goldGrid,
      purpleGrid: ctx.publicInfo?.purpleGrid ?? ctx.purpleGrid,
      totalGrid: ctx.publicInfo?.totalGrid ?? ctx.totalGrid ?? ctx.totalGrids,
      totalGrids: ctx.totalGrids,
      roundingMode: ctx.roundingMode
    });
    const exactStates = (exactRaw.states || []).map((s) => ({
      g: s.G ?? s.g,
      p: s.P ?? s.p,
      r: s.R ?? s.r,
      G: s.G ?? s.g,
      P: s.P ?? s.p,
      R: s.R ?? s.r,
      gold: { unconstrained: true, matches: [] },
      purple: { unconstrained: true, matches: [] }
    }));
    const expanded = g.expandStatesForValuation(ctx, exactStates);
    const componentRows = expanded.map((state) => {
      const component = g.stateComponents(ctx, state);
      return component ? {
        state,
        component,
        weight: g.candidateStateWeight(state, ctx)
      } : null;
    }).filter(Boolean);
    const profile = usedShared.buildProbabilityProfile(ctx, expanded, {
      records: recs,
      componentRows,
      stateComponentsFn: g.stateComponents
    });
    const compact_profile = compactProfile(profile, {
      exactStates: exactStates.map((s) => ({ G: s.g, P: s.p, R: s.r })),
      expandedStates: expanded.map((s) => ({ G: s.g, P: s.p, R: s.r }))
    });
    const datasetRevision = req.datasetRevision || ctx.datasetRevision || null;
    const codeRevision = req.codeRevision || ctx.codeRevision || null;
    const pipelineResult = usedEngine.solveAuctionPipeline(
      Object.assign({}, ctx, { probabilityProfile: compact_profile }),
      recs,
      { datasetRevision, codeRevision, runtime: runtimeName || "live_shadow_compute" }
    );
    const supportCaptureEnvelope = buildSupportCaptureEnvelope(
      profile,
      expanded,
      pipelineResult.predictionSnapshot || null,
      req.captureContext || null
    );
    return {
      ok: true,
      insufficient: false,
      exactStates: exactStates.map((s) => ({ G: s.g, P: s.p, R: s.r })),
      expandedStates: expanded.map((s) => ({ G: s.g, P: s.p, R: s.r })),
      probabilityProfile: compact_profile,
      predictionSnapshot: pipelineResult.predictionSnapshot || null,
      frozenPrediction: pipelineResult.frozenPrediction || null,
      supportCaptureEnvelope,
      computeHost: runtimeName || "live_shadow_compute"
    };
  }

  return {
    compactProfile,
    normalizeCtx,
    buildSupportCaptureEnvelope,
    compute
  };
});
