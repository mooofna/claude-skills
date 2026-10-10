# Anki setup, import and study (for the user)

What the user does in Anki. Explain the relevant part when it first matters (first import, first exam-practice cards, first leech review) instead of all at once.

## One-time settings

- Use Anki desktop 23.10 or newer (and a current mobile app); FSRS scheduling is built in from that version on. Turn FSRS on in the deck options (the switch applies to the whole collection).
- Every deck an import creates gets the **Default** options preset; a package cannot carry its own. So put the study settings into the Default preset and apply it with *Save to all subdecks*. Suggested values: desired retention 0.90; learning steps `10m`; new cards per day as the user's time allows; *Bury new siblings* and *Bury review siblings* on (cloze notes have several cards); leech threshold 6 with leech action *Tag only*, so leeches are tagged for the feedback loop instead of suspended; maximum interval 365 days; new card gather order *Deck*, review sort order *Due date, then random*.
- About three weeks before an exam, give that course's deck its own preset (a clone of Default with desired retention 0.93 to 0.95) with *Save to all subdecks*; switch back after the exam.
- After about 1000 reviews, use *Optimize* in the preset to fit FSRS to the user's history, and repeat every few weeks.

## Importing

- File > Import, choose the `.apkg` (or double-click it). On the first import of a lecture the defaults are fine; it creates the lecture's subdeck.
- Re-import after corrections: set *Update notes* to **Always** and keep *Update note types* on. Notes are matched by their stable id, so review history survives.
- A re-import never moves existing cards to another deck and never deletes notes. Retired cards are listed in the build report; delete them in the browser (search `CardID:<id>`), or let Claude do it through an AnkiConnect MCP server.
- Never rename a lecture deck or the course deck in the card files after an import: Anki would create a second deck.

## Studying

- Study from the course deck (or a parent deck above several courses), not from a single lecture deck. Anki then mixes the due reviews of all lectures and introduces new cards lecture by lecture. Open a single lecture deck only to catch up on that lecture.
- A lecture deck that schedules differently from the others is not on the Default preset: open its options and pick Default.

## Exam-practice cards

- Cards marked as exam practice go into the subdeck `<course deck>::Exam practice`. Once per course, right after the import that creates it, open its options, add a preset named **Hold** with *New cards/day* = 0 and save it for this subdeck only (not *Save to all subdecks*). Studying the course deck then skips these cards.
- Release (Claude says when a lecture is due under the course's rule): in the browser, run the search printed in the build report (`"deck:<course deck>::Exam practice" tag:<base>::L03`), select all, *Change Deck* to the lecture subdeck, and tell Claude, who records the release so later exam cards of that lecture go straight to the lecture subdeck.
- Before the exam, release whatever is still held: select all in the Exam practice subdeck and *Change Deck*, or switch its preset back to Default.
- If a lecture was imported before its exam cards were marked, move them once: search `tag:<base>::exam-practice "deck:<course deck>::L03*"`, *Change Deck* to the Exam practice subdeck. Review history moves with the cards.

## AnkiConnect and an MCP server (optional)

Statistics, leech rewrites and deletions can run through Claude when Anki is reachable:

1. In Anki: Tools > Add-ons > Get Add-ons, code `2055492159` (AnkiConnect), restart Anki.
2. Connect an MCP server that talks to AnkiConnect to Claude (several open-source servers exist); Anki must be open while Claude uses it.

Without it, the feedback loop still works: the user runs the browser search `tag:leech deck:"<course deck>"` and pastes the card ids.

## Troubleshooting

- *"no Anki/profile.md here"*: the scripts were given a folder that is not a course folder; pass the course folder, not `Anki/cards`.
- *Validator error "candidate f2 not on slide 17"*: the figure ids changed because `slides.py prepare` ran on a different version of the PDF. Pick again on `Anki/build/<pdf-stem>/contact/p017.png`, or use `clip:`.
- *MathJax does not render in Anki*: a `$` slipped through or a cloze deletion ends in `}}}`; the validator and the proof check catch both.
- *An import created a second copy of a deck*: a deck name changed after an import (profile `deck:` or `decks.json`). Rename the deck in Anki to the new name, or move the cards.
