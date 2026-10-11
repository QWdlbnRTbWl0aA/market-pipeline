"""Offline quota admission and rolling-window recovery estimates."""
import datetime as dt
import math

WINDOW = 86400
BUFFER = .25


def integer(value):
    try:
        value = int(value)
        return value if value >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def quota_view(dated, state, settings, current):
    reserve = settings.get('quota_reserve', 10)
    local_limit = settings.get('local_daily_request_budget', 100)
    provider_limit = integer(state.get('limit_per_day'))
    if settings.get('quota_reserve_percent') is not None:
        reserve=math.ceil((provider_limit or 0)*settings['quota_reserve_percent']/100)
    # Without a provider observation, admit only the single bootstrap request
    # needed to discover headers; never invent the provider's daily allowance.
    provider_ceiling=max(0,provider_limit-reserve) if provider_limit is not None else local_limit if local_limit is not None else 1
    ceiling=min(local_limit,provider_ceiling) if local_limit is not None else provider_ceiling
    key_id = state.get('key_id')
    events = [(stamp.timestamp(), event) for stamp, event in dated
              if not event.get('key_id') or event.get('key_id') == key_id]
    active = sorted(stamp for stamp, _ in events if 0 <= current-stamp < WINDOW)
    local_slots = max(0, ceiling-len(active))
    local_until = current
    if len(active) >= ceiling:
        local_until = active[len(active)-ceiling]+WINDOW+BUFFER if ceiling > 0 else None
    observed = state.get('quota_observed_at', 0)
    remaining = integer(state.get('remaining_today'))
    anchor_used = integer(state.get('daily_anchor_used'))
    if anchor_used is None and provider_limit is not None and remaining is not None:
        anchor_used = max(0, provider_limit-remaining)
    # Credit only completed successful local requests that were inside the last
    # observed provider window. Unknown/shared-key usage is not credited early.
    expires = []
    for stamp, event in events:
        if not 0 <= observed-stamp < WINDOW or event.get('http_status') != 200:
            continue
        try:
            finished = dt.datetime.fromisoformat(event['finished_at']).timestamp()
            if finished <= observed:
                expires.append(finished+WINDOW+BUFFER)
        except (ValueError, TypeError, KeyError):
            continue
    expires.sort()
    if anchor_used is not None:
        expires = expires[-anchor_used:] if anchor_used else []  # Keep later expiries if history exceeds provider use.
    credited = sum(expiry <= current for expiry in expires)
    provider_until = current
    projected = None
    if remaining is not None and observed:
        projected = min(provider_limit, remaining+credited) if provider_limit is not None else remaining+credited
        if current >= observed+WINDOW+BUFFER:
            projected = provider_limit  # Previous observed consumption has aged out; live headers re-anchor it.
        if projected is not None and projected <= reserve:
            needed = reserve+1-remaining
            provider_until = expires[needed-1] if 0 < needed <= len(expires) else observed+WINDOW+BUFFER
    cooldown = state.get('blocked_until', 0)
    # An actual challenge is never automatically retried by a running client.
    deadlines = [current, provider_until, cooldown]
    if local_until is not None:
        deadlines.append(local_until)
    available_at = max(deadlines) if ceiling > 0 else None
    wait = max(0, available_at-current) if available_at is not None else None
    provider_slots = max(0, projected-reserve) if projected is not None else local_slots
    ready = ceiling > 0 and wait == 0 and local_slots > 0 and provider_slots > 0
    reasons = []
    if not local_slots: reasons.append('Local/provider rolling daily ceiling reached')
    if projected is not None and projected <= reserve: reasons.append('Server-reported daily quota reserve reached')
    if cooldown > current: reasons.append('Saved Etsy Retry-After cooldown')
    return {'provider_limit': provider_limit, 'configured_local_limit': local_limit, 'reserve': reserve,'reserve_percent':settings.get('quota_reserve_percent'),
            'effective_daily_ceiling': ceiling, 'local_key_requests_24h': len(active),
            'last_observed_remaining': integer(state.get('daily_anchor_remaining', remaining)),
            'projected_remaining': projected, 'credited_expired_local_requests': credited,
            'safe_requests_available': min(local_slots, provider_slots) if ready else 0,
            'ready': ready, 'wait_seconds': wait,
            'next_available_at': dt.datetime.fromtimestamp(available_at, dt.timezone.utc).isoformat() if available_at is not None else None,
            'reasons': reasons, 'estimate_scope': 'Offline rolling-window estimate from saved attempts and provider headers; Etsy bucket boundaries and other key users are unknown. Rechecked before each request.'}
