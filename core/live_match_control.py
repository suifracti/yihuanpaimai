"""Apply acknowledged GUI edits before another live frame can overwrite them."""
import copy
from current_match import FACT_KEYS, is_missing_observation


class LiveMatchControl:
    def __init__(self):
        self.match_id = None
        self.overrides = {}
        self.awaiting_exit = False

    def apply(self, command, current, publisher, pipeline, session, *, bootstrap=False):
        if not isinstance(command, dict):
            return False
        revision = command.get("revision")
        if type(revision) is not int or revision < 0:
            return False
        if revision <= publisher.control_revision and not (bootstrap and publisher.sequence == 0):
            return False
        snapshot = command.get("snapshot")
        if not isinstance(snapshot, dict) or not snapshot.get("id"):
            return False
        patch = command.get("facts") or {}
        if not isinstance(patch, dict):
            return False
        if (publisher.sequence > 0 and command.get("expectedMatchId") != current.id
                and snapshot["id"] != current.id):
            return False
        reset = command.get("reset") is True
        cleared_fields = [key for key in (command.get("clearedFields") or []) if key in FACT_KEYS]
        restore_auto_fields = [key for key in (command.get("restoreAutoFields") or []) if key in FACT_KEYS]
        if reset or current.id != snapshot["id"]:
            current.begin_next_match()
            current.id = snapshot["id"]
            current.apply_facts(snapshot, source="manual", intent="snapshot")
            if isinstance(snapshot.get("fieldStates"), dict):
                current.restore_field_states(snapshot.get("fieldStates"))
            self.overrides = {}
        for key in restore_auto_fields:
            self.overrides.pop(key, None)
        for key, value in patch.items():
            if key not in FACT_KEYS:
                continue
            if key in cleared_fields:
                self.overrides[key] = copy.deepcopy(value)
                continue
            if is_missing_observation(key, value):
                continue
            self.overrides[key] = copy.deepcopy(value)
        for key in cleared_fields:
            self.overrides[key] = None
        current.apply_facts(
            {k: v for k, v in self.overrides.items() if k not in restore_auto_fields},
            source="manual",
            intent="confirm",
            cleared_fields=cleared_fields,
            restore_auto_fields=restore_auto_fields,
        )
        self.match_id = current.id
        if reset:
            pipeline.reset_session_state()
            session.active = False
            self.awaiting_exit = True
        publisher.control_revision = revision
        return True

    def apply_to_frame(self, ctx, current, session=None):
        if self.awaiting_exit:
            scene = ctx.get("scene")
            left = scene in {"AUCTION_LOBBY", "CITY_TYCOON_HUB", "CITY_LEISURE_MENU", "OPEN_WORLD"}
            if not left:
                return {"scene": "UNKNOWN", "inAuction": False, "isSettlement": False,
                        "controlPendingExit": True, "recordStableKey": current.id}
            self.awaiting_exit = False
        if session is not None:
            session.observe(ctx, current)
        if self.match_id is not None and self.match_id != current.id:
            self.overrides = {}
            self.match_id = current.id
        ctx.update(copy.deepcopy(self.overrides))
        # Manual corrections must replace the nested copy read by valuation too.
        detail_keys = ("privateBidCap", "bidActionCount", "sparkle", "knownBlue", "knownGreen", "knownWhite", "totalItems", "totalGrid", "goldGrid", "purpleGrid", "redGrid", "goldTotal",
                       "blueCount", "blueAvg", "blueGrid", "greenCount", "greenAvg", "greenGrid",
                       "whiteCount", "whiteAvg", "whiteGrid")
        if any(key in self.overrides for key in detail_keys):
            public = dict(ctx.get("publicInfo") or {})
            public.update({key: copy.deepcopy(self.overrides[key]) for key in detail_keys if key in self.overrides})
            ctx["publicInfo"] = public
        if "totalGrid" in self.overrides:
            ctx["totalGrids"] = self.overrides["totalGrid"]
        cost_keys = {"entryCost": "entry", "intelCost": "intel", "otherCost": "other",
                     "futureIncrementalCost": "futureIncrementalCost"}
        if any(key in self.overrides for key in cost_keys):
            from session_costs import costs_from_facts
            raw = ctx.get("costs") if isinstance(ctx.get("costs"), dict) else {}
            facts = {key: raw.get(dest, ctx.get(key)) for key, dest in cost_keys.items()}
            for key in cost_keys:
                if key in self.overrides:
                    facts[key] = self.overrides[key]
            if facts["entryCost"] is None and "entryCost" not in self.overrides:
                facts["entryCost"] = ctx.get("lobbyEntryCost")
            ctx["costs"] = costs_from_facts(facts)
        if ctx.get("isSettlement"):
            settlement = dict(ctx.get("settlementData") or {})
            if "welfareReceived" in self.overrides:
                settlement["welfare"] = {"received": self.overrides["welfareReceived"]}
            for key, dest in (("isAcquired", "acquired"), ("didCurrentUserAcquire", "acquired"),
                              ("winner", "winner"), ("clearingPrice", "clearingPrice"),
                              ("actualTotal", "actualTotal"), ("realizedProfit", "profit")):
                if key in self.overrides:
                    settlement[dest] = self.overrides[key]
            ctx["settlementData"] = settlement
        return ctx
