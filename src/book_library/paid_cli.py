"""CLI wiring for deliberately enabled, metered features."""
from . import public_config


def add_parsers(subparsers):
    for name, actions in [('semantic', ['status', 'estimate', 'enable', 'disable']),
                          ('review', ['status', 'enable', 'disable']),
                          ('budget', ['status', 'configure'])]:
        command = subparsers.add_parser(name, help={'semantic': 'Configure optional OpenAI semantic search',
            'review': 'Choose automatic metadata review for future imports',
            'budget': 'Inspect or explicitly accept library spending limits'}[name])
        command.add_argument('action', choices=actions, nargs='?', default='status')
        command.add_argument('--accept-budget', action='store_true', help='Accept the displayed/suggested limits ($10 initial/$10 monthly for new libraries)')
        command.add_argument('--initial-usd')
        command.add_argument('--monthly-usd')
        command.add_argument('--timezone')
        command.add_argument('--approval-evidence', default='Explicit library command-line choice')
    return subparsers


def run(lib, args):
    from . import semantic_library
    from .budget import Budget
    action = args.action
    budget_changes = args.accept_budget or args.initial_usd is not None or args.monthly_usd is not None or args.timezone is not None
    if action in ('status', 'estimate', 'disable') and budget_changes:
        raise ValueError('Use budget configure or an enable command to accept spending limits.')
    if args.command == 'budget':
        if action == 'configure':
            if not (args.accept_budget or args.initial_usd is not None or args.monthly_usd is not None):
                raise ValueError('Accept the suggested limits with --accept-budget or supply dollar limits.')
            public_config.ensure_budget(lib, accept=args.accept_budget,
                initial_usd=args.initial_usd, monthly_usd=args.monthly_usd, timezone=args.timezone,
                approval_evidence=args.approval_evidence)
        return {**Budget(lib.state).report(), 'settings': public_config.settings_status(lib)}
    if action == 'enable':
        public_config.ensure_budget(lib, accept=args.accept_budget,
            initial_usd=args.initial_usd, monthly_usd=args.monthly_usd, timezone=args.timezone,
            approval_evidence=args.approval_evidence)
        if args.command == 'semantic':
            return semantic_library.configure_engine(lib, 'openai', approval_evidence=args.approval_evidence)
        return public_config.set_review_default(lib, True, approval_evidence=args.approval_evidence)
    if args.command == 'review':
        if action == 'disable':
            return public_config.set_review_default(lib, False, approval_evidence=args.approval_evidence)
        return public_config.settings_status(lib)
    if action == 'disable':
        return semantic_library.disable_engine(lib)
    if action == 'estimate':
        return semantic_library.estimate_index(lib, engine='openai')
    return {**semantic_library.status(lib), 'settings': public_config.settings_status(lib)}
