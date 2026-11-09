"""Credits scoped to one immutable source passage, never its neighbors."""
from __future__ import annotations


def passage_credit(passage_id, edits):
    """Return a display credit and its evidence, or None to inherit the section."""
    explicit = edits.get((passage_id, 'attribution'))
    if explicit:
        return {'attribution': explicit['value'], 'event': explicit}
    bibliography = edits.get((passage_id, 'bibliography'), {})
    value = bibliography.get('value', {})
    if value.get('type') == 'scripture':
        return scripture_credit(value, bibliography)
    if 'authors' not in value:
        return None
    event = bibliography.get('field_events', {}).get('authors', bibliography)
    people = value['authors']
    if people:
        from .citations import _display
        name = '; '.join(_display(person) for person in people)
    elif people == [] and event.get('status') == 'confirmed' and event.get('evidence'):
        name = 'No named contributor in source'
    else:
        name = 'Contributor unverified'
    return {'attribution': name, 'event': event}


def scripture_credit(value, bibliography):
    """A translation credit is not a claim about the biblical text's author."""
    def confirmed(field):
        event = bibliography.get('field_events', {}).get(field, bibliography)
        return bool(value.get(field)) and event.get('status') == 'confirmed' and bool(event.get('evidence'))
    translation = value.get('bible_translation')
    verified = all(confirmed(field) for field in ('type', 'scripture_scope', 'bible_translation'))
    pure = value.get('scripture_scope') == 'text_only'
    limitations = []
    if not pure:
        name = 'Mixed Scripture and other material — separate credits required'
        limitations.append('Scripture scope requires verification; this target includes other material or has not been confirmed as biblical text only.')
    elif not confirmed('type') or not confirmed('scripture_scope'):
        name = 'Scripture classification requires verification'
        limitations.append('Scripture classification is provisional or disputed; verify the complete passage boundary.')
    elif not confirmed('bible_translation'):
        name = 'Scripture — translation unverified'
        limitations.append('Bible translation requires verification; the biblical text is not a commentary contributor’s work.')
    else:
        short = value.get('bible_translation_short') if confirmed('bible_translation_short') else None
        name = 'Scripture — ' + (short or translation)
    return {'attribution': name, 'event': bibliography, 'kind': 'scripture',
            'verified': verified and pure, 'limitations': limitations}


def credit_limitations(limitations, credit):
    """Replace only inherited attribution warnings; retain all source limits."""
    if credit is None:
        return list(limitations)
    inherited = ('Section contributor requires verification;',
                 'Passage contributor requires verification;')
    result = [warning for warning in limitations if not warning.startswith(inherited)]
    if credit.get('kind') == 'scripture':
        return result + credit.get('limitations', [])
    event = credit['event']
    if (credit['attribution'].startswith('Contributor unverified') or
            event.get('status') != 'confirmed' or not event.get('evidence')):
        result.append('Passage contributor requires verification; the recorded credit is unknown, provisional, or disputed.')
    return result
