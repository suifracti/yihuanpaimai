"""Lobby replenishment using the existing named Host actions and receipts."""

KINDS = {'OpenToolSetup', 'RequestToolRefill', 'ConfirmToolRefill', 'CloseToolSetup', 'BrowseToolGroups', 'SelectToolGroup'}
SCENES = {'LOBBY', 'TOOL_SETUP', 'TOOL_REFILL_CONFIRM', 'TOOL_GROUPS'}


def advance(state, view, send, config):
    """Return True after configured stock was read and setup was closed."""
    stock = state.setdefault('restock', {'step': 0, 'spent': 0})
    scene = view.get('publishedScene')
    pending, receipt = stock.get('pending'), view.get('preparationReceipt') or {}
    if pending and all(receipt.get(k) == pending.get(k) for k in
            ('intentId', 'kind', 'matchId', 'matchGeneration', 'observationSessionId', 'round')):
        if receipt.get('status') in {'UNKNOWN', 'NOT_SENT'}:
            stock.pop('pending', None)
            if pending['kind'] == 'CloseToolSetup' and scene == 'LOBBY':
                stock['ready'] = True
            state.update(phase=stock.get('resumePhase','idle'),
                         reason='INSTRUMENT_'+str(receipt.get('reason') or receipt['status']))
            if stock.get('ready'):
                return True
    if scene not in SCENES:
        if stock.get('ready') and (scene == 'SETTLEMENT' or
                (scene in {'AUCTION','AUCTION_READY','INSTRUMENT_LIST','INSTRUMENT_GOLD_SELECTED','INSTRUMENT_PURPLE_SELECTED'}
                 and (view.get('engine') or {}).get('round', 0) >= 1)):
            stock['leftLobby'] = True
        return stock.get('ready') is True
    if stock.get('leftLobby'):
        cycle = stock.get('cycle', 0) + 1
        stock.clear()
        stock.update(step=0, spent=0, cycle=cycle)
    if stock.get('ready') or state.get('phase') == 'stopped':
        return stock.get('ready') is True
    stock.setdefault('resumePhase', state.get('phase') if state.get('phase') == 'return_confirmed' else 'idle')

    def stop(reason):
        state.update(phase='stopped' if 'FLOOR' in reason else 'restocking', reason=reason, resendAllowed=False)
        return False

    if not isinstance(config, dict):
        return stop('INSTRUMENT_CONFIG_INVALID')
    targets = config.get('instrumentTargets', {'goldAverage': 1, 'purpleCount': 1})
    floor = config.get('minimumFunds', 100000)
    if (type(floor) is not int or floor < 0 or not isinstance(targets, dict)
            or any(k not in {'goldAverage', 'purpleCount'} or type(v) is not int or v < 0
                   for k, v in targets.items())):
        return stop('INSTRUMENT_CONFIG_INVALID')
    if type(view.get('currentFunds')) is int:
        stock['funds'] = view['currentFunds']
    pending = stock.get('pending')
    if pending:
        receipt = view.get('preparationReceipt') or {}
        if any(receipt.get(k) != pending.get(k) for k in
               ('intentId', 'kind', 'matchId', 'matchGeneration', 'observationSessionId', 'round')):
            return False
        status = receipt.get('status')
        if status in {'UNKNOWN', 'NOT_SENT'}:
            return stop('INSTRUMENT_' + str(receipt.get('reason') or status))
        if status != 'CONFIRMED':
            return False
        stock.pop('pending')
        if pending['kind'] == 'OpenToolSetup':
            stock.pop('browsed', None)  # Each reopened list starts at its first group.
        if pending['kind'] == 'ConfirmToolRefill':
            stock['spent'] += pending['amount']
        if pending['kind'] == 'CloseToolSetup':
            stock['ready'] = True
            state.update(phase=stock['resumePhase'], reason='INSTRUMENTS_READY')
            return True
    funds = stock.get('funds')
    if view.get('foreground') is not True:
        state.update(phase='restocking', reason='GAME_NOT_FOREGROUND')
        return False
    if type(funds) is not int:
        return stop('INSTRUMENT_FUNDS_UNREADABLE')
    if funds < floor:
        return stop('INSTRUMENT_FUNDS_BELOW_FLOOR')
    inventory = view.get('instruments') or {}
    if scene == 'LOBBY':
        kind, cost = 'OpenToolSetup', None
    elif scene == 'TOOL_GROUPS':
        if view.get('advancedToolGroupVisible') is True:
            kind, cost = 'SelectToolGroup', None
        elif stock.get('browsed'):
            return stop('INSTRUMENT_ADVANCED_GROUP_NOT_FOUND')
        else:
            kind, cost = 'BrowseToolGroups', None
            stock['browsed'] = True
    elif scene == 'TOOL_SETUP':
        if any(type(inventory.get(k)) is not int for k, n in targets.items() if n):
            return stop('INSTRUMENT_STOCK_UNREADABLE')
        if all(inventory.get(k, 0) >= n for k, n in targets.items()):
            kind, cost = 'CloseToolSetup', None
        else:
            cost = inventory.get('refillCost')
            if type(cost) is not int or cost <= 0:
                return stop('INSTRUMENT_TARGET_UNAVAILABLE_OR_PRICE_UNREADABLE')
            if stock.get('refilled'):
                return stop('INSTRUMENT_TARGET_NOT_REACHED')
            if funds - cost < floor:
                return stop('INSTRUMENT_REFILL_WOULD_CROSS_FUNDS_FLOOR')
            stock['before'] = inventory.get('goldAverage', 0)
            stock['purpleBefore'] = inventory.get('purpleCount', 0)
            kind, cost = 'RequestToolRefill', None
    else:
        cost = inventory.get('refillCost')
        if type(cost) is not int or cost <= 0 or funds - cost < floor:
            return stop('INSTRUMENT_CONFIRM_PRICE_OR_FUNDS_INVALID')
        kind = 'ConfirmToolRefill'
        stock['refilled'] = True
    engine = dict(view['engine'], matchId='lobby-' + view['engine']['observationSessionId'],
                  matchGeneration=1, round=0)
    stock['step'] += 1
    intent = dict(engine, intentId=f"restock-{engine['observationSessionId']}-{stock.get('cycle',0)}-{stock['step']}-{kind}",
                  kind=kind, amount=cost, budget=max(1, funds-floor), minimumFunds=floor,
                  goldStockBefore=stock.get('before', 0), deadlineNs=view['nowNs']+3_000_000_000,
                  purpleStockBefore=stock.get('purpleBefore', 0),
                  fundsBefore=funds,
                  takeoverGeneration=0, leaseId='lobby', window=view['window'],
                  approvalId=view['approvalId'])
    stock['pending'] = intent
    state.update(phase='restocking', reason='WAITING_' + kind.upper(), preparationIntent=intent)
    envelope = dict(type='domain.action.dispatch', protocolVersion=1, requestId='dispatch-'+intent['intentId'],
                    bootId=view['bootId'], observationSessionId=engine['observationSessionId'], intent=intent)
    if send(None, envelope) is not True:
        return stop('INSTRUMENT_DISPATCH_NOT_ACCEPTED')
    return False
