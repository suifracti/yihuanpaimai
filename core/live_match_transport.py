"""Versioned worker snapshots; reject reordered frames and retired match IDs."""
import copy
import uuid

from current_match import FACT_KEYS


class LiveMatchSession:
    """Retire a match only after an observed exit, not temporary window loss."""
    def __init__(self):
        self.active = False

    def observe(self, ctx, current_match):
        scene = ctx.get("scene")
        if scene in {"IN_AUCTION", "SETTLEMENT"}:
            self.active = True
        exit_seen = scene in {"AUCTION_LOBBY", "CITY_TYCOON_HUB", "CITY_LEISURE_MENU", "OPEN_WORLD"}
        exit_seen = exit_seen or (scene == "AUCTION_LOADING" and ctx.get("loadingDirection") in {"to_lobby", "egress"})
        if self.active and exit_seen:
            current_match.begin_next_match()
            self.active = False
        for key in ("id", "matchId", "recordStableKey"):
            ctx[key] = current_match.id


class LiveMatchPublisher:
    def __init__(self):
        self.session = uuid.uuid4().hex
        self.sequence = 0
        self.control_revision = 0
        self.awaiting_exit = False

    def attach(self, payload, current_match):
        self.sequence += 1
        result = dict(payload)
        result["visionState"] = {
            "version": 1, "session": self.session, "sequence": self.sequence,
            "controlRevision": self.control_revision,
            "controlPendingExit": self.awaiting_exit,
            "snapshot": copy.deepcopy(current_match.snapshot()),
        }
        return result


class LiveMatchReceiver:
    """One receiver per worker connection; UI-owned occupancy stays local."""
    def __init__(self):
        self.session = None
        self.sequence = 0
        self.match_id = None
        self.retired = set()

    def apply(self, state, current_match, minimum_control_revision=0):
        if not isinstance(state, dict) or state.get("version") != 1:
            return False
        revision = state.get("controlRevision", 0)
        if type(revision) is not int:
            return False
        session, sequence, snapshot = state.get("session"), state.get("sequence"), state.get("snapshot")
        if not isinstance(session, str) or not session or type(sequence) is not int:
            return False
        if (self.session is not None and session != self.session) or sequence <= self.sequence:
            return False
        if not isinstance(snapshot, dict) or snapshot.get("schemaVersion") != 7:
            return False
        match_id = snapshot.get("id")
        status = snapshot.get("lifecycleStatus")
        if not isinstance(match_id, str) or not match_id or match_id in self.retired:
            return False
        if status not in {"DRAFT", "FINALIZED"}:
            return False
        if self.match_id and self.match_id != match_id:
            self.retired.add(self.match_id)
        if current_match.id != match_id:
            if self.match_id is not None or not current_match.has_any_fact():
                current_match.begin_next_match()
            current_match.id = match_id
        # GUI capture completion is independent of worker frame observations.
        # Full snapshots are state transfer: nulls must not clear existing facts.
        facts = {key: copy.deepcopy(snapshot[key]) for key in FACT_KEYS
                 if key in snapshot and key != "warehouseOccupancy"}
        current_match.apply_facts(facts, source="vision", intent="snapshot")
        current_match.lifecycle_status = status
        origin = snapshot.get("dataOrigin") or snapshot.get("executionOrigin")
        if origin:
            current_match.data_origin = origin
        current_match.created_at = snapshot.get("createdAt") or current_match.created_at
        current_match.updated_at = snapshot.get("updatedAt") or current_match.updated_at
        self.session, self.sequence, self.match_id = session, sequence, match_id
        return True
