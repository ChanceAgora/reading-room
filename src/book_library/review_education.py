"""Plain-language field meanings shared by guided reviews and AI instructions."""
from __future__ import annotations

TEXT_TYPE_GUIDE = {
    'scripture': {'label': 'Bible text', 'definition': 'The biblical text itself, rather than someone explaining it.', 'example': 'A reading from Luke 1.'},
    'commentary': {'label': 'Commentary or explanation of a text', 'definition': 'Writing that interprets or discusses another text.', 'example': 'An explanation of what a passage from Isaiah means.'},
    'poetry': {'label': 'Poetry', 'definition': 'A poem or verse presented as a literary work.', 'example': 'A poem printed with its own title and lines.'},
    'quotation': {'label': 'Quoted material', 'definition': 'A separately presented quotation from another work or speaker.', 'example': 'An attributed extract from a sermon by another writer.'},
    'caption': {'label': 'Picture caption', 'definition': 'Words identifying or explaining a picture or illustration.', 'example': 'The title and description beneath a painting.'},
    'translation_note': {'label': 'Note about a translation', 'definition': 'A note explaining how words have been translated.', 'example': 'A footnote explaining an alternative translation of a Hebrew word.'},
    'editorial': {'label': 'Introduction or editorial explanation', 'definition': 'Writing that introduces, organizes, or explains how to use a book or section. This category does not identify its author.', 'example': 'An introduction describing the book’s purpose and arrangement.'},
    'index': {'label': 'Index', 'definition': 'An alphabetical or organized list pointing to locations in a book.', 'example': 'A subject index with page references.'},
    'reference': {'label': 'Reference material', 'definition': 'Information arranged for looking things up, such as a bibliography or reference entry.', 'example': 'A list of books cited or a dictionary entry.'},
    'prose': {'label': 'Other prose', 'definition': 'Ordinary paragraph writing when none of the more specific categories fits well.', 'example': 'A narrative or discussion that is not an introduction or commentary.'},
    'mixed': {'label': 'Several kinds of writing', 'definition': 'This part contains more than one distinct kind of material.', 'example': 'Bible readings followed by commentary and a poem.'},
    'unknown': {'label': 'Not classified yet', 'definition': 'We have not chosen a category. The material can still be read and searched.', 'example': 'A section whose full contents have not been inspected.'},
}

TEXT_TYPE_RULES = (
    'Classify the TARGET material, not supporting publication pages. Choose by purpose: '
    'editorial for an introduction explaining purpose, arrangement, or use; commentary for '
    'interpretation of another text; prose is the fallback when a more useful specific '
    'category does not fit. A purpose-based classification is an evidence-backed judgment '
    'and need not be literally printed as a genre label. Multiple headings do not alone '
    'establish multiple content types or prevent a uniform classification. Use mixed '
    'when the inspected target actually demonstrates distinct kinds of material. Do not '
    'classify a whole section as Scripture merely because it quotes a Bible verse. '
    'Classification never establishes a contributor identity or citation format. State '
    'what was inspected and distinguish uncertainty from missing database information.'
)

# question, purpose, effect, action label
FIELD_GUIDE = {
    'title': ('What should this be called on screen?', 'A clear title helps you recognize this book or section.', 'Changes its label in browsing and reading views. The citation title is separate.', 'Use this title'),
    'author': ('Whose name should appear with this book?', 'This is the credit you see while browsing.', 'Updates the displayed credit. Author, editor, and translator roles in citations remain separate.', 'Use this credit'),
    'attribution': ('Who wrote this part?', 'A section may have a different writer from the editors of its book.', 'Updates the name shown for this part. A citation credit is a separate related change.', 'Use this credit'),
    'text_type': ('What kind of writing is this?', 'This helps you find introductions, poems, Bible readings, and similar material later.', 'Adds a search category. It does not identify the author or determine the citation format.', 'Use this category'),
    'notes': ('Is there anything useful to remember?', 'An optional note can preserve a question or explanation for later.', 'Saves an editorial note; it does not establish authorship or verify other details.', 'Keep this note'),
    'bibliography.title': ('What title should appear in citations?', 'A citation should name the book or particular contribution you used.', 'Changes the title printed in citations; the on-screen label can be updated separately.', 'Use this title'),
    'bibliography.short_title': ('Would a shorter citation title help?', 'Repeated citations can use a shorter recognizable title.', 'Changes the short title in repeated citations, not the full title.', 'Use this short title'),
    'bibliography.authors': ('Who should the citation credit as the writer?', 'Credit the person who wrote this book or this particular part.', 'Changes citation authors. Book editors are not automatically authors of every contribution.', 'Use this writer credit'),
    'bibliography.editors': ('Who edited the whole book?', 'Editors assemble or oversee a book that may contain work by many writers.', 'Adds editor credits to book citations; it does not make them the writers of individual sections.', 'Use these editor credits'),
    'bibliography.translators': ('Who translated this material?', 'A translator’s contribution is credited separately from the writer’s.', 'Changes the translation credit. A section can inherit the book’s translator unless its own credit differs.', 'Use this translation credit'),
    'bibliography.publisher': ('Who published this book?', 'The publisher helps identify the publication you used.', 'Changes the publisher in book citations and inherited publication details.', 'Use this publisher'),
    'bibliography.year': ('When was this edition published?', 'Use the publication year, which can differ from the download or export date.', 'Changes the publication year in citations for this copy.', 'Use this publication year'),
    'bibliography.edition': ('Which edition is this?', 'An edition statement can identify a revised version of a book.', 'Changes the edition description in citations. A format change alone need not mean revised contents.', 'Use this edition statement'),
    'bibliography.volume': ('Which volume of the set is this?', 'Some works are published in several numbered volumes.', 'Adds or changes the volume number in citations.', 'Use this volume number'),
    'bibliography.volume_title': ('Does this volume have its own title?', 'A volume can have a title in addition to the larger work’s title.', 'Changes the volume title in citations.', 'Use this volume title'),
    'bibliography.url': ('Which web record identifies this copy?', 'A stable source link helps you return to a matching publication record.', 'Changes the source link used for this publication.', 'Use this source link'),
    'bibliography.doi': ('Does this work have a permanent DOI?', 'A DOI is a permanent identifier assigned to a publication; many books do not have one.', 'Adds the DOI to citations when applicable. Leaving it blank is fine when none is known.', 'Use this DOI'),
    'bibliography.format': ('What format is the copy you read?', 'A printed book, EPUB, and PDF can be different formats of the same work.', 'Records the format consulted; it does not prove that all versions have identical contents.', 'Use this format'),
    'bibliography.type': ('How should this part be cited?', 'A chapter, poem, reference entry, and Bible reading use different citation patterns.', 'Changes the citation format for this part. This is separate from its search category.', 'Use this citation format'),
    'bibliography.scripture_scope': ('Is this just Bible text or does it include commentary?', 'Bible text and a scholar’s explanation need different credits.', 'Helps prevent a citation from treating commentary as Scripture.', 'Use this citation scope'),
    'bibliography.bible_translation': ('Which Bible translation is quoted?', 'The source’s translation statement identifies the Bible wording you are reading.', 'Changes the Bible translation named in citations; it does not identify the commentary writer.', 'Use this Bible translation'),
    'bibliography.bible_translation_short': ('How should the Bible translation be abbreviated?', 'An abbreviation is a shorter name for a known translation.', 'Changes the abbreviated translation label used in citations.', 'Use this abbreviation'),
    'isbn': ('Are these records describing the same book?', 'ISBNs identify publications and formats. Different numbers do not by themselves prove different contents.', 'This comparison helps identify your copy. Keeping the recorded number makes no metadata change.', 'Keep this ISBN'),
}


def field_education(key, label='', help_text='', example=''):
    """Return useful guidance for every supported field without new jargon."""
    optional = key == 'text_type' or key == 'notes' or key.startswith('profile.') or key == 'bibliography.short_title'
    if key.startswith('profile.'):
        title = label or key.split('.', 1)[1].replace('_', ' ')
        question = f'Would {title.lower()} labels help you find this later?'
        purpose = help_text.split(' Use labels supported')[0] or 'Optional labels can make related material easier to find.'
        effect = 'Updates only this set of research labels. It does not change the book or citation credits.'
        action = 'Use these labels'
    else:
        question, purpose, effect, action = FIELD_GUIDE.get(key, (
            f'What should we record for {(label or key).lower()}?', help_text or 'This describes the material you are reviewing.',
            'Updates this detail only; other information is kept.', 'Use this detail'))
    return {'question': question, 'purpose': purpose, 'effect': effect, 'example': example,
            'priority': 'optional' if optional else 'important', 'action_label': action}
