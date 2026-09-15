"""Collect an already completed GUI prediction before saving a settlement."""
import asyncio
import uuid
from websockets.exceptions import ConnectionClosed


class PredictionArchiveTransport:
    def __init__(self, send, current_match, holder, timeout=2.0):
        self.send = send
        self.current_match = current_match
        self.holder = holder
        self.timeout = timeout
        self.pending = {}

    async def collect(self, ctx):
        match_id = str(ctx.get("id") or ctx.get("matchId") or "")
        if not match_id or match_id != self.current_match.id:
            return False
        request_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = (match_id, future)
        try:
            await self.send({"type": "prediction_archive_request", "requestId": request_id,
                             "matchId": match_id})
            await asyncio.wait_for(future, self.timeout)
        except (asyncio.TimeoutError, OSError, ConnectionClosed):
            # A missing GUI response must not discard observed settlement facts.
            pass
        finally:
            self.pending.pop(request_id, None)
        return self.current_match.id == match_id

    def receive(self, data):
        pending = self.pending.get(data.get("requestId"))
        if not pending:
            return False
        match_id, future = pending
        if data.get("matchId") != match_id or future.done():
            return False
        snapshot = data.get("snapshot")
        if self.current_match.id == match_id and isinstance(snapshot, dict) and snapshot.get("matchId") == match_id:
            self.holder.update(match_id, snapshot=snapshot, frozen_prediction=data.get("frozenPrediction"))
        future.set_result(None)
        return True
