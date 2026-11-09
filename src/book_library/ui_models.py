"""Public JSON contracts for the React interface.

The library's extensible evidence records remain JSON objects. Page-level fields
and the records used across screens have explicit schemas; extra source fields
are retained rather than silently discarded during presentation.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter


class Record(BaseModel):
    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)


class Book(Record):
    id: str
    title: str = ""
    author: str = ""


class Focus(Record):
    id: str
    name: str = ""
    description: str = ""
    subjects: list[str] = Field(default_factory=list)
    forms: list[str] = Field(default_factory=list)
    books: list[str] = Field(default_factory=list)
    breadth: str = "balanced"


class SearchHit(Record):
    id: str
    title: str = ""
    text: str = ""
    attribution: str = ""
    location: str = ""
    reason: str = ""


class SearchResult(Record):
    direct: list[SearchHit] = Field(default_factory=list)
    connections: list[SearchHit] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    coverage: dict[str, JsonValue] = Field(default_factory=dict)


class CatalogResult(Record):
    books: list[Book]
    total: int
    offset: int
    limit: int
    sort: str = "title"
    has_more: bool


class SourceBlock(Record):
    id: str = ""
    kind: str
    text: str = ""
    location: str | None = None
    attribution: str | None = None


class Reading(Record):
    blocks: list[SourceBlock] = Field(default_factory=list)


class Citation(Record):
    full_note: str = ""
    short_note: str = ""
    bibliography: str = ""
    warnings: list[str] = Field(default_factory=list)


class ReviewDraft(Record):
    target_id: str
    revision: str
    version: int
    changes: dict[str, JsonValue] = Field(default_factory=dict)
    suggestions: list[dict[str, JsonValue]] = Field(default_factory=list)
    stale: bool = False


class ReviewField(Record):
    key: str
    label: str
    kind: str
    current_display: str
    edit_value: str
    edit_evidence: str
    edit_verified: bool
    dom_id: str


class SearchData(Record):
    q: str
    selected_focus: str
    mode: str
    filters: dict[str, str]
    focuses: list[Focus]
    result: SearchResult | None
    engine: str


class BooksData(Record):
    books: list[Book]
    result: CatalogResult
    q: str
    facet: str
    sort: str
    next_url: str | None
    previous_url: str | None


class BookData(Record):
    work: Book
    section_offset: int
    outline: dict[str, JsonValue] | None


class ReadData(Record):
    reading: Reading
    context: int
    saved: bool


class UnitData(Record):
    reading: Reading
    saved: bool


class SelectionData(Record):
    selection: dict[str, JsonValue]
    action: Literal["cite", "record"]
    saved: bool


class CitationData(Record):
    citation: Citation
    passage: dict[str, JsonValue]
    section: dict[str, JsonValue]
    locator: dict[str, JsonValue]
    locator_type: str
    locator_value: str
    saved: bool
    segment_id: str


class UnitCitationData(Record):
    citation: Citation
    scope: Literal["unit", "selection"]
    target_id: str
    target_title: str
    back_url: str
    locator: dict[str, JsonValue]


class BibliographyData(Record):
    target: dict[str, JsonValue]
    fields: dict[str, str]
    roles: list[str]
    inherited_translators: list[dict[str, JsonValue]]
    passage_id: str
    saved: bool
    unchanged: bool


class ReviewData(Record):
    review: dict[str, JsonValue]
    target: dict[str, JsonValue]
    draft: ReviewDraft
    groups: dict[str, list[ReviewField]]
    field_map: dict[str, ReviewField]
    guidance: list[dict[str, JsonValue]]
    current_recommendation: dict[str, JsonValue] | None
    pending: list[dict[str, JsonValue]]
    message: str
    error: str
    review_url: str
    request_id: str
    busy: bool


class IntakeListData(Record):
    listing: dict[str, JsonValue]


class IntakeDetailData(Record):
    job: dict[str, JsonValue]
    counts: dict[str, int]
    target_page: dict[str, JsonValue]
    change_page: dict[str, JsonValue]
    can_pause: bool
    can_request_review: bool = False
    can_resume: bool
    can_undo: bool
    refresh_url: str
    message: str
    error: str


class TaxonomyData(Record):
    vocabulary: dict[str, JsonValue]
    next_url: str | None
    previous_url: str | None


class TaxonomyBooksData(Record):
    result: CatalogResult
    label: str
    sort: str
    first_page_url: str
    next_url: str | None
    previous_url: str | None


class TaxonomyTermData(Record):
    term: dict[str, JsonValue]
    relation_labels: dict[str, list[str]]
    creating: bool
    saved: bool
    error: str | None
    action: str


class FocusesData(Record):
    focuses: list[Focus]


class FocusData(Record):
    focus: dict[str, JsonValue]
    focus_id: str
    saved: bool


class FocusBooksData(Record):
    focus: Focus
    books: list[Book]
    result: CatalogResult
    q: str
    sort: str
    offset: int
    saved: bool
    next_url: str | None
    previous_url: str | None


class MetadataData(Record):
    work: Book
    target: dict[str, JsonValue]
    target_id: str
    fields: list[str]
    saved: bool
    section_offset: int
    suggestion_kinds: dict[str, str]
    text_types: list[str]


class HistoryData(Record):
    entries: list[dict[str, JsonValue]]


class StatusData(Record):
    status: dict[str, JsonValue]
    synced: bool


class IllustrationData(Record):
    illustration: dict[str, JsonValue]


class ErrorData(Record):
    message: str


class Page(BaseModel):
    title: str
    nav: str = ""


# Each discriminator ties a view to its actual data contract in generated TS.
class SearchPage(Page):
    page: Literal["search"]
    data: SearchData


class BooksPage(Page):
    page: Literal["books"]
    data: BooksData


class BookPage(Page):
    page: Literal["book"]
    data: BookData


class ReadPage(Page):
    page: Literal["read"]
    data: ReadData


class UnitPage(Page):
    page: Literal["unit"]
    data: UnitData


class SelectionPage(Page):
    page: Literal["selection"]
    data: SelectionData


class CitationPage(Page):
    page: Literal["citation"]
    data: CitationData


class UnitCitationPage(Page):
    page: Literal["unit_citation"]
    data: UnitCitationData


class BibliographyPage(Page):
    page: Literal["bibliography"]
    data: BibliographyData


class ReviewPage(Page):
    page: Literal["review"]
    data: ReviewData


class IntakeListPage(Page):
    page: Literal["intake_list"]
    data: IntakeListData


class IntakeDetailPage(Page):
    page: Literal["intake_detail"]
    data: IntakeDetailData


class TaxonomyPage(Page):
    page: Literal["taxonomy"]
    data: TaxonomyData


class TaxonomyBooksPage(Page):
    page: Literal["taxonomy_books"]
    data: TaxonomyBooksData


class TaxonomyTermPage(Page):
    page: Literal["taxonomy_term"]
    data: TaxonomyTermData


class FocusesPage(Page):
    page: Literal["focuses"]
    data: FocusesData


class FocusPage(Page):
    page: Literal["focus"]
    data: FocusData


class FocusBooksPage(Page):
    page: Literal["focus-books"]
    data: FocusBooksData


class MetadataPage(Page):
    page: Literal["metadata"]
    data: MetadataData


class HistoryPage(Page):
    page: Literal["history"]
    data: HistoryData


class StatusPage(Page):
    page: Literal["status"]
    data: StatusData


class IllustrationPage(Page):
    page: Literal["illustration"]
    data: IllustrationData


class ErrorPage(Page):
    page: Literal["error"]
    data: ErrorData


UiPage = Annotated[Union[
    SearchPage, BooksPage, BookPage, ReadPage, UnitPage, SelectionPage,
    CitationPage, UnitCitationPage, BibliographyPage, ReviewPage,
    IntakeListPage, IntakeDetailPage, TaxonomyPage, TaxonomyBooksPage,
    TaxonomyTermPage, FocusesPage, FocusPage, FocusBooksPage, MetadataPage,
    HistoryPage, StatusPage, IllustrationPage, ErrorPage,
], Field(discriminator="page")]
PAGE_ADAPTER = TypeAdapter(UiPage)


class UiRedirect(BaseModel):
    redirect: str


class UiBootstrap(BaseModel):
    csrf: str


class UiAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    fields: dict[str, str | list[str]] = Field(default_factory=dict, max_length=200)


class UiError(BaseModel):
    error: str


UiResponse = Union[UiPage, UiRedirect]
