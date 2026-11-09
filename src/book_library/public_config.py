"""Explicit paid-feature choices, separate from credentials and library contents."""
from __future__ import annotations

from contextlib import nullcontext
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .storage import atomic_json, jsonl, now, read_json, writer

SETTINGS_VERSION = 1


def read_settings(state):
    value = read_json(state / 'config.json', {})
    if not isinstance(value, dict):
        raise ValueError('Library configuration must be a JSON object.')
    return value


def detected_timezone():
    try:
        target = str(Path('/etc/localtime').resolve())
        if '/zoneinfo/' in target:
            return validate_timezone(target.split('/zoneinfo/', 1)[1])
    except (OSError, ValueError):
        pass
    return 'UTC'


def validate_timezone(value):
    if not isinstance(value, str) or not value or len(value) > 100:
        raise ValueError('Use an IANA timezone such as America/Chicago or UTC.')
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError('Use a valid IANA timezone such as America/Chicago or UTC.') from None
    return value


def dollars(value):
    if isinstance(value, bool):
        raise ValueError('A spending limit must be a nonnegative dollar amount.')
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('A spending limit must be a nonnegative dollar amount.') from None
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise ValueError('A spending limit must be a nonnegative dollar amount with at most two decimal places.')
    return str(amount)


def _evidence(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 4000:
        raise ValueError('Provide brief explicit authorization evidence (1–4000 characters).')
    return value.strip()


def _legacy_paid_authorization(state, config=None):
    """Recognize historical paid consent, never ordinary catalog/text records."""
    config = read_settings(state) if config is None else config
    semantic = config.get('semantic', {})
    if semantic.get('full_build_approved') is True and semantic.get('engine') == 'openai':
        return True
    if any(event.get('kind') == 'reserve' and event.get('scope') in ('initial', 'monthly')
           for event in jsonl(state / 'costs.jsonl')):
        return True
    for path in (state / 'intakes').glob('*.json'):
        auth = read_json(path, {}).get('authorization', {})
        if (auth.get('kind') == 'explicit_intake' and auth.get('review') == 'every_indexed_heading'
                and 'semantic' not in auth):
            return True
    return False


def is_existing_library(lib):
    """Data-preservation detection is deliberately broader than paid consent."""
    return any((lib.state / name).exists() for name in
               ('catalog.json', 'current.json', 'taxonomy.json', 'costs.jsonl', 'defaults-initialized.json')) or any((lib.state / 'intakes').glob('*.json'))


def initialize(lib, timezone=None, *, locked=False):
    """Set safe defaults only for genuinely fresh state; never grant permission."""
    if timezone is not None:
        validate_timezone(timezone)
    with nullcontext() if locked else writer(lib.state):
        config = read_settings(lib.state)
        if 'settings_version' not in config and not _legacy_paid_authorization(lib.state, config):
            config['settings_version'] = SETTINGS_VERSION
            config.setdefault('budget', {'initial_usd': '10', 'monthly_usd': '10',
                                         'timezone': timezone or detected_timezone(), 'accepted_at': None})
            config.setdefault('metadata_review', {'enabled': False})
            config.setdefault('semantic', {'enabled': False})
            atomic_json(lib.state / 'config.json', config)
    return settings_status(lib)


def budget_settings(state):
    config = read_settings(state)
    saved = config.get('budget', {})
    if not isinstance(saved, dict):
        raise ValueError('Budget settings must be a JSON object.')
    legacy = ('settings_version' not in config and not saved and
              _legacy_paid_authorization(state, config))
    fresh = not legacy
    return {'initial_usd': dollars(saved.get('initial_usd', '10' if fresh else '50')),
            'monthly_usd': dollars(saved.get('monthly_usd', '10' if fresh else '25')),
            'timezone': validate_timezone(saved.get('timezone', 'UTC' if fresh else 'America/Chicago')),
            'accepted_at': saved.get('accepted_at'),
            'legacy': legacy}


def require_budget(state):
    """Legacy accounting stays usable; fresh libraries require explicit acceptance."""
    settings = budget_settings(state)
    if not settings['accepted_at'] and not settings['legacy']:
        raise ValueError('Accept spending limits first: library budget configure --accept-budget. Local reading and manual editing remain available.')
    return settings


def accept_budget(lib, *, initial_usd=None, monthly_usd=None, timezone=None,
                  approval_evidence='Explicit spending-limit acceptance'):
    evidence = _evidence(approval_evidence)
    initialize(lib)
    with writer(lib.state):
        config = read_settings(lib.state)
        previous = budget_settings(lib.state)
        config['budget'] = {**config.get('budget', {}),
                            'initial_usd': dollars(initial_usd if initial_usd is not None else previous['initial_usd']),
                            'monthly_usd': dollars(monthly_usd if monthly_usd is not None else previous['monthly_usd']),
                            'timezone': validate_timezone(timezone or previous['timezone']),
                            'accepted_at': now(), 'approval_evidence': evidence}
        atomic_json(lib.state / 'config.json', config)
    return settings_status(lib)


def ensure_budget(lib, *, accept=False, initial_usd=None, monthly_usd=None, timezone=None,
                  approval_evidence='Explicit paid-feature setup'):
    initialize(lib)
    if accept or initial_usd is not None or monthly_usd is not None:
        return accept_budget(lib, initial_usd=initial_usd, monthly_usd=monthly_usd,
                             timezone=timezone, approval_evidence=approval_evidence)
    if timezone is not None:
        raise ValueError('Changing the accounting timezone requires explicit budget acceptance.')
    require_budget(lib.state)
    return settings_status(lib)


def set_review_default(lib, enabled, *, approval_evidence='Explicit automatic-review choice'):
    if type(enabled) is not bool:
        raise ValueError('The automatic-review default must be true or false.')
    initialize(lib)
    evidence = _evidence(approval_evidence)
    if enabled:
        require_budget(lib.state)
    with writer(lib.state):
        config = read_settings(lib.state)
        config['metadata_review'] = {**config.get('metadata_review', {}), 'enabled': enabled,
                                     'approval_evidence': evidence, 'approved_at': now()}
        atomic_json(lib.state / 'config.json', config)
    return settings_status(lib)


def settings_status(lib):
    config = read_settings(lib.state)
    semantic = config.get('semantic', {})
    review = config.get('metadata_review', {})
    budget = budget_settings(lib.state)
    return {'settings_version': config.get('settings_version'),
            'semantic_enabled': bool(semantic.get('enabled') and semantic.get('full_build_approved')),
            'semantic_engine': semantic.get('engine'),
            'automatic_metadata_review': review.get('enabled') is True,
            'budget': budget,
            'budget_accepted': bool(budget['accepted_at'] or budget['legacy']),
            'review_default_scope': 'future intakes only; existing jobs retain their authorization'}


def migrate_legacy(lib, *, approval_evidence, automatic_review=True):
    """An explicit owner-authorized migration, never inferred from an API key."""
    evidence = _evidence(approval_evidence)
    if not is_existing_library(lib):
        raise ValueError('Legacy migration requires an existing library.')
    with writer(lib.state):
        config = read_settings(lib.state)
        previous = budget_settings(lib.state)
        config.setdefault('budget', {'initial_usd': previous['initial_usd'],
                                     'monthly_usd': previous['monthly_usd'], 'timezone': previous['timezone'],
                                     'accepted_at': now(), 'approval_evidence': evidence})
        config.setdefault('metadata_review', {'enabled': bool(automatic_review),
                                              'approval_evidence': evidence, 'approved_at': now()})
        config.setdefault('settings_version', SETTINGS_VERSION)
        atomic_json(lib.state / 'config.json', config)
    return settings_status(lib)
