"""Explicit acquisition evidence shared by live state and history."""

from typing import Any, Mapping, Optional


class AcquisitionNameTracker:
    """Match-local, fresh-frame exact-name corroboration; never uses bid values."""
    def __init__(self):
        self.configured_name = ''
        self.reset(None)

    def set_player_name(self, name):
        if name != self.configured_name:
            self.configured_name = name
            self.winner = None
            self.winner_count = 0
            self.winner_frame = None
            self.value = None

    def reset(self, key):
        self.key = key
        self.names = {}
        self.winner = None
        self.winner_count = 0
        self.winner_frame = None
        self.value = None

    def bind(self, key):
        if key != self.key:
            self.reset(key)

    def evidence(self):
        return {
            "method": "CONFIGURED_EXACT_NAME_V1" if self.configured_name else "MATCH_LOCAL_EXACT_NAMES_V1", "recordStableKey": self.key,
            "configuredPlayerName": self.configured_name or None,
            "acquired": self.value, "winner": self.winner,
            "winnerSamples": min(2, self.winner_count),
            "roster": [{"slot": slot, "name": row[0], "samples": min(2, row[1])}
                       for slot, row in sorted(self.names.items())],
        }

    def observe_name(self, slot, name, frame):
        if not self.key or slot not in (1, 2, 3, 4) or not name:
            return
        old_name, count, last_frame = self.names.get(slot, (None, 0, None))
        if frame == last_frame:
            return
        self.names[slot] = (name, count + 1 if name == old_name else 1, frame)
        if self.value is not None and self._roster_result(self.winner) != self.value:
            self.value = None

    def _roster_result(self, name):
        stable = {slot: value[0] for slot, value in self.names.items() if value[1] >= 2}
        matching = [slot for slot, candidate in stable.items() if candidate == name]
        all_matching = [slot for slot, value in self.names.items() if value[0] == name]
        if self.configured_name:
            if stable.get(4) and stable[4] != self.configured_name:
                return None
            if any(slot != 4 and row[0] == self.configured_name for slot, row in self.names.items()):
                return None
            if len(all_matching) > 1:
                return None
            return name == self.configured_name
        if stable.get(4) and len(matching) == 1 and len(all_matching) == 1:
            return matching[0] == 4
        return None

    def observe_winner(self, name, confidence, ambiguous, frame):
        if ambiguous:
            self.value = None
        if not self.key or not name or confidence < .85 or ambiguous:
            self.winner_count = 0
            return self.value
        if frame == self.winner_frame:
            return self.value
        self.winner_frame = frame
        if name != self.winner:
            self.winner, self.winner_count = name, 1
            self.value = None  # A conflicting fresh reading revokes automatic certainty.
        else:
            self.winner_count += 1
        if self.winner_count >= 2:
            self.value = self._roster_result(name)
        return self.value


def acquired_bool(value: Any) -> Optional[bool]:
    return value if isinstance(value, bool) else None


def acquisition_from_context(ctx: Mapping[str, Any]) -> tuple[bool, Optional[bool]]:
    """Return presence and value; missing observations must not clear prior evidence."""
    settlement = ctx.get("settlement")
    settlement_data = ctx.get("settlementData")
    for source, keys in (
        (settlement, ("acquired", "isAcquired", "didCurrentUserAcquire")),
        (ctx, ("isAcquired", "didCurrentUserAcquire", "acquired")),
        (settlement_data, ("acquired", "isAcquired", "didCurrentUserAcquire")),
    ):
        if isinstance(source, Mapping):
            for key in keys:
                if key in source:
                    return True, acquired_bool(source[key])
    return False, None
