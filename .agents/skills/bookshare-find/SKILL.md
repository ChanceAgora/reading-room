---
name: bookshare-find
description: "Find and compare Bookshare books on a subject, by author or title, or against the user's local or Logos library. Use for Bookshare searches and shortlists before downloading; a generic request to use Bookshare starts here."
---

# Bookshare Find

Find worthwhile, accessible books for the user's actual research purpose and
return a reviewable shortlist. This skill searches; use `bookshare-download`
when the user has authorized acquisition. A request to create or revise these
skills does not itself authorize book downloads.

## Scope and current holdings

Infer the subject, purpose, and desired breadth from the request and current
project. This skill works for any subject, not only theological research.
Ask only when missing information materially changes the search. Honor a
requested count; otherwise give a compact set of strong candidates without
padding to a quota.

Use [library-search](../library-search/SKILL.md) to check the shared index's
freshness and search current local holdings first. Synchronize when needed;
do not reread the entire catalog or reopen all originals. Match title,
author/editor, edition, volume, actual coverage, and acquisition records;
a different Bookshare ID can describe the same edition. Verify ambiguous
matches in the source. Mark usable existing copies as already local and link
them instead of recommending duplicates. Use an appropriate editable research
focus for the subject; an honest local holdings gap is a useful search input.

Use https://app.logos.com when the user requests a Logos comparison or it would
materially help identify missing books or editions. Distinguish **Library**
ownership from Store/catalog availability. Verify the actual edition; an older
Bookshare copy is not interchangeable with a newer owned Logos resource. Report
current price/value comparisons only when verified, with date and currency;
do not infer price or ownership from a title's presence in search results.

## Search Bookshare

Prefer an available Bookshare connector if it supports the needed actions;
otherwise use supported browser tools. Reuse an existing signed-in Bookshare
tab where practical, honoring the user's browser choice. Do not assume an
ambient tab is logged in. Inspect the visible session and controls; do not
hardcode old selectors, cookies, download endpoints, or private APIs.

Search the catalog using subject synonyms and useful authors, then narrow by
exact title and ISBN for ambiguous editions or series volumes. Basic search
covers bibliographic information and synopsis keywords; use the separate
Advanced Search full-text field when searching inside books would help.
Multiple advanced fields can narrow results too far. Inspect active language,
quality, date, and other filters before treating an empty search as absence.
See [Bookshare search and availability notes](references/search.md) when needed.

Open promising book records and inspect author/editor, publisher, date, ISBN,
edition/volume, synopsis or contents, and available formats. Account and region
can affect access: distinguish a public catalog match from an available
signed-in download. If login is needed, ask the user to sign in in the browser;
continue useful public research and local comparisons meanwhile. Do not ask
for his password. Public search snippets are leads, not availability proof.

Judge usefulness from the actual evidence available. Say when fit is inferred
from a synopsis or contents rather than reading the book. Look for distinct
contributions, not many near-duplicates. Flag edition uncertainty and missing
volumes. Catalog metadata can be wrong; download inspection later must confirm
actual publisher front matter and contents.

## Deliver and hand off

Use a concise numbered shortlist, with each item including:

- Title, author/editor, edition or volume and year when verified.
- Direct Bookshare record link and stable book ID.
- Why it helps this subject or project, including a useful distinction from
  neighboring candidates.
- Current text-format availability, or an honest availability limitation.
- Already-local status and material edition, coverage, or Logos differences.

Suggest a likely format when useful: usable text EPUB and Word are both strong
choices, with the actual package and research needs deciding. Do not initiate a
download just to inspect a format, and do not download several formats by default.

For a substantial comparison, save a concise dated shortlist in the current
project's research area so a later request such as “download 2, 4, and 6” resolves
to the exact titles, IDs, and editions. Keep numbering stable during that handoff.
For a small search, the conversation's numbered links suffice.

If the user asked only to find or review books, stop with the shortlist. If the
same request already authorizes downloads of selected titles or a defined set
such as “download your best three,” continue with the installed
[bookshare-download skill](../bookshare-download/SKILL.md) without asking again.
Otherwise wait for the user's selection; a recommendation is not authorization.
