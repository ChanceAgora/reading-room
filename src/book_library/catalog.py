"""Presentation and ordering for the catalog, without changing source metadata."""
from __future__ import annotations

import unicodedata


def normalized(value):
    return ''.join(char for char in unicodedata.normalize('NFKD', str(value or '')).casefold()
                   if not unicodedata.combining(char))


def creator_names(book):
    """Use only book-level bibliographic creators, in their recorded order."""
    bibliography = book.get('bibliography') or {}
    for role in ('authors', 'editors', 'translators'):
        names = bibliography.get(role)
        if isinstance(names, list):
            names = [name for name in names if isinstance(name, dict) and
                     any(name.get(part) for part in ('literal', 'family', 'given'))]
            if names:
                return role, names
    return None, []


def display_name(name):
    return name.get('literal') or ' '.join(str(name.get(part) or '').strip()
                                         for part in ('given', 'family')).strip()


def creator_text(book):
    bibliography = book.get('bibliography') or {}
    names = [name for role in ('authors', 'editors', 'translators')
             for name in bibliography.get(role) or [] if isinstance(name, dict)]
    return ' '.join([str(book.get('author') or ''), *(display_name(name) for name in names)])


def sort_key(book, sort='title'):
    title = normalized(book.get('title'))
    stable = str(book.get('id') or '')
    if sort == 'title':
        return title, stable
    _, names = creator_names(book)
    if names:
        name = names[0]
        first = normalized(name.get('literal') or name.get('family') or name.get('given'))
        second = '' if name.get('literal') else normalized(name.get('given'))
    else:
        # A literal credit is not a license to infer a culturally specific surname.
        first, second = normalized(book.get('author')), ''
    return not bool(first), first, second, title, stable


def summary(book):
    metadata = book.get('metadata') or {}
    bibliography = book.get('bibliography') or {}
    credit = book.get('author') or ''
    if not credit:
        role, names = creator_names(book)
        credit = '; '.join(display_name(name) for name in names)
        if credit and role != 'authors':
            credit = ('Edited by ' if role == 'editors' else 'Translated by ') + credit
    return {**book,
            'catalog_credit': credit,
            'catalog_edition': bibliography.get('edition') or book.get('edition') or metadata.get('edition'),
            'catalog_year': bibliography.get('year') or book.get('year') or metadata.get('publication_year') or metadata.get('year')}


def page(books, *, sort='title', offset=0, limit=50):
    if sort not in ('title', 'creator'):
        raise ValueError('Choose title or creator ordering.')
    offset = max(0, int(offset))
    limit = max(1, min(int(limit), 100))
    ordered = sorted(books, key=lambda book: sort_key(book, sort))
    total = len(ordered)
    selected = [summary(book) for book in ordered[offset:offset + limit]]
    return {'books': selected, 'total': total, 'offset': offset, 'limit': limit,
            'sort': sort, 'has_more': offset + len(selected) < total}
