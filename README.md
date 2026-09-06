# locheck

Checks a candidate localisation plist against the version before it and says
whether it is safe to ship.

```bash
pip install -e .
locheck                          # compares the two newest versions in this folder
locheck new.plist                # compare against the release it replaces
locheck old.plist new.plist      # spell both out
```

No terminal: double-click `check-localisations.bat`, or drag `.plist` files onto
it. Flags: `--details --all --summary --json --strict`. Exit `0` clean, `1`
blockers, `2` unreadable. Tests: `pip install -e ".[dev]" && pytest` (270).

## The problem I picked

Not "what changed" — `diff` does that, and the brief calls it the floor. The
question on Monday morning is **which changes could break the game.** So the job
is separating *changed* from *dangerous*. My measure: on these files four strings
changed and only two deserve attention. A tool reporting four would be worse than
none.

## The idea it rests on

Rules judge one string in isolation — *is this wrong right now?* — and know
nothing about the previous release. The engine runs **every rule twice**, against
the older file and against the newer, and compares:

| older | newer | verdict |
|---|---|---|
| fine | broken | **regression** — blocks the release |
| broken | broken | **pre-existing** — hidden by default |
| broken | fine | **fixed** — shown in green |

Pass an older file as the candidate and it detects the **rollback** and rewords
everything for it — verdict, headings and each finding. A crash that "was fixed"
shipping forward is one that *comes back* rolling back, and reading the forward
wording in that direction is how you ship the fire you were putting out.

That is `engine._classify`, and it is the whole difference from a diff. It also
catches the trap in the data: French went `Commence dans % ...` →
`Commence dans %u...`. Placeholders changed, so a naive check screams — but the
old one was broken and the new one matches the source. Reported as **fixed**.

A new check is one predicate; the three-way classification comes free.

## How I chose the checks

Severity is **what the player experiences**, not how big the edit was: crash or
blank = BLOCKER; a language vanishes or the release never lands = HIGH; wrong or
badly wrapped content = MEDIUM.

Twenty checks: placeholders (malformed, parity, order), empty strings,
`A:[a/b]` tokens (unbalanced, missing, wrong option count), languages dropped
from a key or the whole file, removed or duplicated text IDs, entries with no
`en-US`, an unbumped version, invalid language codes, translations left stale by
a reworded source, partial language coverage, missing numbers, lost line breaks,
length outliers, and stray whitespace at a string's edges.

## What it does **not** catch

- **Whether a string fits its button.** It counts characters; real overflow needs
  font and widget width. Biggest gap, and the thing I want most.
- **Meaning.** A fluent mistranslation is invisible.
- **Whether a removed ID is still requested by a shipped client.**
- **`tk` is Turkmen; the strings are Turkish (`tr`).** Not flagged — `tk` is
  valid, catching it needs language detection, and it is pre-existing.
- Numbers below ten, and grapheme-vs-codepoint length for emoji.
- **Meaning inside a number.** The Japanese pool rules say the multiplier
  decreases "to a maximum of 4" where the source says "to a minimum of 1.0".
  Every digit is present, just attached to the wrong word - no comparison of
  values can see that.

## Smallest version, then what

**v1** was the diff engine, four blocker checks and the fixed/pre-existing
classification — about an hour, already above the floor. I built the classifier
*first* because leaving it out is how the tool becomes noise. Then line numbers
and fix instructions; the quieter content checks; a false-positive corpus; the
summary-first view; and file discovery so it runs with no arguments.

## Trade-offs

- **One finding per string**, other problems attached to it. One row in the table
  (the ship/no-ship count), all of them in the card (the fix).
- **Numbers below ten ignored.** The check flagged the Turkish pool rules, which
  write "Rack 1"/"Rack 2" as *İlk üçgen*/*İkinci üçgen* — a correct translation
  reported as broken. Costs a dropped `0.5`; keeps MEDIUM worth reading.
- **A `%` after a digit is a percent sign.** `50% off` was being reported as a
  type clash. Every real corruption here has a *letter* before the sign.
- **Only two-letter language codes judged.** `fil`, `haw` have no two-letter form.
- **Pre-existing problems hidden** (`--all` shows them) — real, but showing them
  at release time is how a checklist becomes noise.
- **Ambiguity refused, not guessed.** A confident report about the wrong pair of
  files is worse than a question.

## Not done, deliberately

Config files, per-check toggles, a plugin system, a web UI, spell-checking,
language detection. Twenty checks don't need a framework — a teammate adds one
by writing a function returning a `Problem` and appending it to a list.

I also stopped adding checks: falling catch rate, rising false-positive risk, and
I hit that cost twice in one afternoon.

## Next, with another day

1. **Feed it the UI** — component widths would turn the length heuristic into a
   real overflow check. The one gap that matters.
2. **Compare against production**, not the second-newest file.
3. **Post the summary to the release channel** on every candidate build.

## Assumptions

`en-US` is the source. Strings are format-processed, so a bare `%` is a risk.
`\n` is a literal backslash-n. Filenames carry versions, and **the second-newest
file is the one being replaced** — which can be wrong, so the header always states the pair
it picked and how many it chose between, and `V` re-picks interactively.
