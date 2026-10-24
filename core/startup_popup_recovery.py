"""Dismiss known leftover lobby dialogs once per run, then reread the lobby."""
KNOWN_POPUPS = {'TOOL_REFILL_CONFIRM', 'ENTRY_FEE', 'TOOL_SETUP', 'TOOL_GROUPS'}

def advance(state, view, send):
    recovery = state.setdefault('startupRecovery', {})
    if recovery.get('done') or state.get('phase') == 'stopped':
        return False
    scene = view.get('publishedScene')
    if scene in (None, 'UNKNOWN', 'LOADING'):
        return True
    if scene == 'LOBBY' or (not recovery.get('started') and scene not in KNOWN_POPUPS):
        recovery['done'] = True
        state.pop('restock', None)
        state.update(phase='idle', reason=None)
        return False
    if scene not in KNOWN_POPUPS:
        state.update(phase='stopped', reason='STARTUP_RECOVERY_SCENE_UNKNOWN')
        return True
    pending = recovery.get('pending')
    if pending:
        receipt = view.get('preparationReceipt') or {}
        if any(receipt.get(k) != pending.get(k) for k in
               ('intentId', 'kind', 'matchId', 'matchGeneration', 'observationSessionId', 'round')):
            return True
        if receipt.get('status') not in {'CONFIRMED', 'UNKNOWN', 'NOT_SENT'}:
            return True
        recovery.pop('pending')
    attempts = recovery.setdefault('attempts', {})
    if attempts.get(scene, 0) >= 3:
        state.update(phase='stopped', reason='STARTUP_POPUP_CANCEL_FAILED')
        return True
    attempts[scene] = attempts.get(scene, 0) + 1
    recovery['started'] = True
    engine = dict(view['engine'], matchId='lobby-' + view['engine']['observationSessionId'], matchGeneration=1, round=0)
    intent = dict(engine, kind='CancelKnownPopup', intentId=f"recover-{engine['observationSessionId']}-{scene}-{attempts[scene]}",
                  amount=None, budget=1, recoveryScene=scene, deadlineNs=view['nowNs']+3_000_000_000,
                  takeoverGeneration=0, leaseId='lobby', window=view['window'], approvalId=view['approvalId'])
    recovery['pending'] = intent
    state.update(phase='recovering', reason='CANCELLING_STARTUP_POPUP', preparationIntent=intent)
    envelope = dict(type='domain.action.dispatch', protocolVersion=1, requestId='dispatch-'+intent['intentId'],
                    bootId=view['bootId'], observationSessionId=engine['observationSessionId'], intent=intent)
    if send(None, envelope) is not True:
        state.update(phase='stopped', reason='STARTUP_POPUP_DISPATCH_FAILED')
    return True
