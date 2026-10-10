# The exam summary sheet

Only for courses whose exam allows a summary, cheat or formula sheet, and only where LaTeX is installed (`pdflatex`; `latexmk` is used when present). The sheet is written lecture by lecture, alongside the cards, so it never needs a crash diet before the exam.

## Setting it up

`python scripts/summary.py init <course>` copies the template into `<course>/Summary/` (existing files are kept):

| file | purpose |
|---|---|
| `lectures/L03.tex` | the content, one file per lecture (`X01.tex` for other material); the only files written per session |
| `preamble.tex` | shared layout and macros; course notation macros go at its end |
| `sheet.tex` | the exam sheet: sheet blocks only, two columns, at the minimum font size (11 pt, A4 by default) |
| `reference.tex` | the reference: every block, with source pointers; sheet blocks are marked with a filled square |
| `title.tex` | title of the reference |
| `summary.yaml` | `sheet_pages` (front and back of one sheet = 2), `min_font_pt`, and `targets`: the share of the sheet each lecture may use, e.g. from the exam's topic weights (sums to about 1) |

If the exam's rule differs (another font size or paper format), change `\documentclass[11pt,a4paper]` in `sheet.tex`, the geometry in `preamble.tex`, and `min_font_pt`. Record the rule in the profile.

Outputs: `<Module>-exam-sheet.pdf` (what the user prints), `<Module>-reference.pdf` (everything, for homework and tutorials) and `build/report.md` (each lecture's share of the sheet against its target, and the block list).

## Writing a lecture's blocks

```latex
\lecture{L03}{Singular Value Decomposition}

\begin{sheetblock}{L03.1}{Eckart-Young-Mirsky}
For \(k < r\), \(A_k = \sum_{i \le k} \sigma_i u_i v_i\T\) is the best rank-\(k\) approximation:
\(\|A - A_k\|_2 = \sigma_{k+1}\), \quad \(\|A - A_k\|_F = \sqrt{\sum_{i>k} \sigma_i^2}\).
\slip{The Frobenius error is \(\sigma_{k+1}\).}
\src{slide 7}
\end{sheetblock}

\begin{refblock}{L03.2}{Existence of the SVD}
...
\end{refblock}
```

| macro | effect |
|---|---|
| `\lecture{L03}{Title}` | section header and the anchor the page budget is measured from; one per file |
| `sheetblock{L03.n}{Title}` | printed on the exam sheet and in the reference |
| `refblock{L03.n}{Title}` | printed only in the reference |
| `\refonly{...}` / `\sheetonly{...}` | text only in the reference (explanations) / only on the sheet (a compressed variant) |
| `\src{...}` | source pointer (slide numbers, script theorem), reference only |
| `\slip{...}` | the *wrong* claim a distractor uses, marked with a cross |
| `steps` environment | a numbered procedure |

Content rules:

- Write the blocks before the lecture's cards. Content: formulas with their conditions, recipes for the computations the exams repeat, small tables, and at most one `\slip{...}` line per block naming the wrong claim a distractor uses; never a true statement after the cross.
- Derivations only as a one-line pointer, where the route rebuilds the formula.
- The sheet gets what is long, easy to garble and used across lectures. Definitions, basic rules and recipes the cards keep in the head stay reference-only. Stay near the lecture's target in `summary.yaml`: the sheet is the scarce resource.
- Check every formula against the slide image and the script; the script's notation wins over handwriting.
- Block ids (`L03.1`) belong to their file, are never renumbered or reused (cards point at them), and titles are plain text (cards quote them).
- No font-size or scaling commands (`\small`, `\footnotesize`, `\scalebox`, `\resizebox`, ...): the typed sheet must stay at the minimum font size, and `summary.py` rejects them.

## Building and looking

`python scripts/summary.py build <course>` lints all lecture files (ids, titles, forbidden commands, balanced environments), compiles both PDFs and writes the report; `--strict` also fails when the sheet is over its page budget. Render the sheet to PNG and look at it (legibility, line breaks). If a lecture is far over its target, move material to the reference or compress it with `\sheetonly`.

## Cards and the sheet

A card with `sheet: L03.1` gets the tag `<base>::sheet` and the line "On the exam sheet: L03.1 Eckart-Young-Mirsky" above its `extra`. Core identities named in the profile keep full-recall cards anyway (no time to look them up in the exam); other long formulas on the sheet get cards on structure, conditions and use. If a block moves to the reference, the validator warns about every card that points at it: restore full recall on those cards or put the block back.

The user can add to the sheet at any time ("add X to the sheet"), or edit `Summary/lectures/Lxx.tex` themselves and rebuild.
