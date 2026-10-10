# paper-to-obsidian

A Claude skill for people who write on paper and keep their notes in Obsidian. Take rough phone photos of your pages, hand them to Claude, and get back:

- a word-for-word transcription that keeps your structure (headings, nested bullets, arrows, crossed-out text, hand-drawn checkboxes), with `[?]` wherever a word is uncertain instead of a guess,
- the transcription filed where it belongs: next to the note for that meeting or event, into the daily note for journal pages, with dated lines in the notes of the people and organisations involved,
- your open items pulled out as Markdown tasks or as a plain list for a paper planner,
- the pages kept as an archive PDF that looks like a scan, embedded at the end of the note.

## How it works

`scripts/prepare_pages.py` turns any mix of photos and scans (JPEG, PNG, WebP, TIFF, BMP, GIF, AVIF, HEIC/HEIF, PDF) into clean, ordered page images:

- applies the camera's rotation and orders pages by the time they were taken,
- with `--scan`, finds the sheet in the photo, corrects the perspective, crops away the table and evens out the lighting; every outline is validated first, and if the script is not sure it keeps the whole photo and only fixes the lighting, so nothing on the page is cut off,
- splits dense pages into overlapping halves for reading, and writes the archive PDF.

Claude then reads the pages, transcribes them, searches the vault for the notes they belong to and writes the result. A settings note in the vault (`paper-to-obsidian.md`, template in `references/settings-template.md`) records where the inbox is, how tasks are kept and whether journal pages are transcribed, so later runs need no questions.

```bash
pip install -r requirements.txt
python3 scripts/prepare_pages.py ~/Photos/IMG_*.HEIC -o /tmp/pages --scan --split --pdf "Scans/2026/2026-10-10 Meeting.pdf"
```

## Requirements

Python 3.10 or newer with Pillow. Optional: `pillow-heif` for iPhone photos, `pypdfium2` for PDF input, `opencv-python-headless` and `numpy` for `--scan`. Without an extra, the script says what is missing and carries on with what it can do.

## Privacy

Transcribing a page means its content is read by the model. The settings let you keep journal pages as images only (`journal: embed-only`) or ask before the first one.
