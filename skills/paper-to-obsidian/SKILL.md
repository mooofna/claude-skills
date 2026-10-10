---
name: paper-to-obsidian
description: Turn photos or scans of handwritten pages (meeting and event notes, lecture notes, journal pages, to-do lists) into faithful transcriptions filed into the right notes of an Obsidian vault, with action items extracted and the scan archived. Use when the user uploads or points to photos, scans or PDFs of paper notes, or asks to digitise, transcribe or file handwritten notes into Obsidian. Works with any image format, including iPhone HEIC.
---

# Paper to Obsidian

The user writes on paper and takes rough photos. You turn them into notes in their Obsidian vault: a word-for-word transcription, filed where it belongs, linked to the notes it concerns, with the open items pulled out and the scan kept as the source.

Work through the steps in order. The two things that matter most are a transcription the user can trust and notes that land in the right place.

## 1. Find the vault and its settings

- The vault is the folder that contains `.obsidian/`. If you can reach several, ask which one.
- Look for a settings file named `paper-to-obsidian.md` anywhere in the vault. Read it; it overrides the defaults below.
- No settings file yet: ask the user at most four short questions (inbox folder, how they keep tasks, whether journal pages should be transcribed, the language for summaries), then write the file from `references/settings-template.md` so the next run needs no questions. If the user is not around, use the defaults and say so.

Defaults: inbox `Scans/Inbox`, archive `Scans/{YYYY}/{date} {title}.pdf`, tasks as Markdown checkboxes, journal pages transcribed, summary in the language of the notes, new entity notes only for people or organisations with a follow-up.

## 2. Prepare the pages

Pages come as chat uploads or as files in the inbox folder. Any format is fine: JPEG, PNG, WebP, TIFF, BMP, GIF, AVIF, HEIC/HEIF, PDF.

```bash
python3 scripts/prepare_pages.py <files or folders> -o <work dir>/pages --scan --split \
  --pdf "<vault>/<archive path>"
```

- The script applies the camera rotation, orders pages by capture time (`--order name` or `given` to override), scales them, writes `page-NNN.jpg` plus top and bottom halves (`page-NNNa.jpg`, `page-NNNb.jpg`), a `manifest.json`, and the archive PDF.
- `--scan` makes photos look like scans: it finds the sheet, straightens it, crops away the table and evens out the lighting (white paper, dark ink, printed colour kept). Use it for photos by default; it is what makes the archive PDF look like a scan, and you can read either version. Every outline is checked before anything is cropped. When the script is not sure, it keeps the whole photo and only fixes the lighting, so nothing on the page is lost. The notes in `manifest.json` say for each page `sheet detected, flattened` or `no confident outline, kept full photo`. PDF pages are already scans and stay as they are. `--clean` fixes the lighting only.
- Install what it asks for: `pip install -r requirements.txt` from this skill's folder, or only the parts you need: `pillow` (required), `pillow-heif` for HEIC, `pypdfium2` for PDF input, `opencv-python-headless` and `numpy` for `--scan` and `--clean`. Without OpenCV, `--scan` prints a warning and the pages are prepared as plain photos.
- Read `manifest.json`. Report any file listed under `failed`. If a page comes out sideways, rerun with `--rotate PAGE:90` (or 180, 270); the script turns pages only by the camera's rotation tag, never by guessing.
- If Python is not available, read the images directly and skip the archive PDF; say so in the report.

## 3. Transcribe

For each page: look at the full page once for its layout, then read the words from the halves. Crop and zoom into any line you are not sure about before you write it down.

- **Word for word.** Keep the writer's language, wording, abbreviations and spelling. Do not fix grammar, translate or polish.
- **Structure as written.** Underlined or boxed titles become `##` headings. Bullets and sub-bullets become nested Markdown lists following the indentation. Numbered items stay numbered. Arrows (→ ⇒ ↳ ⟺) and quotation marks stay.
- **Crossed-out text** becomes `~~text~~`.
- **Hand-drawn checkboxes** become `☐` (open) or `☑` (ticked) unless the settings ask for Markdown tasks. They are not converted silently into vault tasks.
- **Uncertain words** get `[?]` right after them; unreadable ones become `[illegible]`. Never guess a name, number, amount, date, email or URL: write what you see and mark it.
- **Drawings, margin arrows, brackets, diagrams:** one plain sentence after the page, for example "In the margin, an arrow links 'stock bought up' to 'symptom-based alert'."
- **Printed decoration** (letterheads, logos, footer art) is not transcribed, but use it as context, for example to name the event.
- **Second pass.** Compare every transcribed line against the image before moving on. Most errors are in names, numbers and short words.

## 4. Decide where it belongs

Classify each page, or each section when a page mixes topics: meeting or conversation, event or talk, lecture, journal, ideas and to-dos, other.

Search before you create. Look through the vault's file names and contents for the event, people, organisations, course and date. If a calendar is connected, check the date for the event's name. Then:

- **One source note per session** holds the transcription. If a note for that meeting or event already exists, create the source note next to it and link both ways; otherwise create it in the folder the settings name, or ask.
- **Journal pages** go into that day's daily note (folder, date format and section from the settings), or, with `journal: embed-only`, only the scan is embedded there.
- **People and organisations** mentioned with a follow-up get one dated line in their existing note, linking to the source note. Create an entity note only when the settings allow it.
- **Existing text is never rewritten or deleted.** Append, or fill empty fields of a template the user prepared.

## 5. Pull out the open items

Collect every action: checkboxes, "I should ...", "ask X", "→ do Y". Use the writer's words, shortened, never invented. Put them where the settings say:

- `tasks: markdown` writes `- [ ]` tasks into the source note (Tasks plugin compatible).
- `tasks: plain-list` writes plain bullets under an "Open items" heading and repeats them in your reply, for people who keep tasks on paper.
- `tasks: none` leaves them in the transcription only.

Mark items the paper shows as still open but that look done (for example a box next to something the notes report as having happened) as "check whether done".

## 6. Write the source note

```markdown
---
title: <Event or meeting>, notes
created: <date of the notes, YYYY-MM-DD>
source: handwritten, <n> pages
scan: "[[<archive path>]]"
related: "[[...]], [[...]]"
---

> [!info] Transcribed word for word from photos. [?] = uncertain reading. Summary and open items are added; everything below "Page 1" is the original text.

# Summary          (optional, in the settings' language, 3 to 6 bullets, facts only)
# Open items
# Page 1: <title on the page>
...
# Scan
![[<archive path>]]
```

Follow the vault's own conventions where they differ (frontmatter keys, heading style, language of headings, date format). Apply any extra style rules listed under `style` in the settings.

## 7. Archive and clean up

- The archive PDF goes to the archive path from the settings and is embedded at the end of the source note.
- Move processed files out of the inbox (into the archive folder) so the inbox only holds new pages. Do not delete originals unless the user asks.

## 8. Report back

Keep it short:
- the notes you created or changed, as links,
- the open items as a plain list,
- every `[?]` with its page, so the user can correct it,
- anything you skipped or could not read.

## Privacy

Journal pages can be personal. Respect the `journal` setting; when it says `ask`, ask before the first journal page is transcribed. Keep private details about other people in the source note only, not in their entity notes, and never put health, financial or similar sensitive details into entity notes.
