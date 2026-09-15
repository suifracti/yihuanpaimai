(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.MascotRuntimeBinding = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const allowedAutomaticStates = Object.freeze(new Set(["idle", "loading", "thinking", "sleep"]));

  function consumeHostMascotState(snapshot) {
    if (!snapshot || snapshot.snapshotVersion !== 1) return null;
    if (!allowedAutomaticStates.has(snapshot.state)) return null;
    if (typeof snapshot.assetId !== "string" || snapshot.assetId.length === 0) return null;
    return Object.freeze({ state: snapshot.state, assetId: snapshot.assetId });
  }

  return Object.freeze({ consumeHostMascotState });
});
