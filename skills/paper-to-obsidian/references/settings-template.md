---
# Settings for the paper-to-obsidian skill. Save as paper-to-obsidian.md anywhere in the vault.
# Paths are relative to the vault root.

inbox: Scans/Inbox                      # where new photos and scans land
archive: Scans/{YYYY}/{date} {title}.pdf  # {YYYY}, {date} (YYYY-MM-DD) and {title} are filled in
notes_folder: ask                       # folder for new source notes when no related note exists, or "ask"

summary: true                           # add a short summary above the transcription
summary_language: same-as-notes         # e.g. English, German, or same-as-notes

tasks: markdown                         # markdown (- [ ] tasks) | plain-list | none
open_items_heading: Open items

journal: transcribe                     # transcribe | embed-only | ask
daily_notes:
  folder: ""                            # "" means the vault root
  format: YYYY-MM-DD
  section: Journal                      # heading in the daily note that receives journal pages

entity_notes: existing-only             # existing-only | create (for people or organisations with a follow-up)
people_folder: ""                       # where new person notes go when entity_notes is create
organisations_folder: ""

style: []                               # extra rules, e.g. ["no em dashes", "dates as DD.MM.YYYY in text"]
---

Notes for the skill (free text). Anything written here is read on every run, for example
"meeting notes from the reading group belong in Reading Group/".
