# AI usage

I used Claude (Opus, in Claude Code) throughout — not as a generator I accepted
from, but as a fast pair who needs checking and is at its most convincing when
wrong.

**What for:** re-explaining the brief in plain terms so I could confirm I had
read it right; exploring the two files; the implementation; the test suites; and
reviewing its own work when I told it to attack the tool rather than the data.

I set the direction: CLI over a web UI, Python, severity tiers, and the
constraint I cared most about — **do not overflag.** I wrote that down before
starting and it drove most of what followed.

## Three things it gave me that I kept

**The regression classifier.** My instinct was "start with a diff". It pushed
back — the diff is the *engine*, not the product — and proposed running each rule
against **both** files, so the same problem reads as regression, pre-existing or
fixed depending on the live version. That is the idea the tool rests on, and what
makes the French `% ...` → `%u...` case report as a fix rather than a risk. I
kept it because I could see why it worked, not because it sounded clever.

**`jp` should be `ja`.** I would not have found this. The new Japanese strings
are filed under the country code for Japan rather than the language code, so
they reach nobody — invisible in a diff, invisible in QA. It is the best single
catch in the submission and it came from the AI reading the file, not from me.

**Line numbers via a second parse.** `plistlib` discards positions, so it
re-parses with `expat` purely to build a line index — what turns "the Russian
string is broken" into `:22`.

## Three things I rejected or made it redo

**The first CLI output.** It told me *that* things were flagged, not *what* or
*where* — no line numbers, no fix. It ran fine and was useless to act on. I sent
it back; the line numbers, detail cards and fix instructions all exist because of
that. Biggest correction I made, and why my working notes say the AI did not do a
great job of making this human-friendly first time.

**The console-width "fix".** I asked for the text to fit the window. It added a
`mode con` resize to the launcher, which pins the console *buffer* — so
maximising the window left the report boxed into the left 120 columns with dead
space beside it. It fixed one thing by breaking another. I made it remove the
resize entirely and let the tool measure the terminal on every render.

**A self-contradicting prompt.** It wrote `Press . (or any key) to expand` —
naming a key, then saying the key does not matter. Now a key legend. Small, but
exactly what survives when nobody reads the output as a user.

## How I verified it

By not taking its word for anything that mattered.

- Claims about the files were checked against the files — it ran a script to
  confirm the seeded bugs rather than asserting from reading.
- I had it build a corpus of **correct** localisation content (European decimal
  commas, promo percentages, CJK, RTL, emoji, markup) and assert the tool stays
  silent. Two false positives fell out immediately.
- I made it run in the shell I actually use. It had verified everything through
  bash; the same command in PowerShell exposed a Windows console crash on
  Cyrillic.
- Where a fix was subtle, I asked for a test named after the bug so it cannot
  quietly return.

## What surprised me

**It wrote a launcher that lied about the result.** The `.bat` called `py -3`,
sent its errors to `nul`, and reported the exit code as a verdict. On this
machine `py -3` is a different Python from the one with the package installed, so
the tool never ran — and the window said *"Blockers found. Do not ship yet."* A
confident verdict for a run that did not happen. Given the whole point of this
tool is trustworthy output, that one stuck with me.

**Its own reference data was wrong.** It built a table of country codes mistaken
for language codes and listed `uk` as "United Kingdom, use `en`". `uk` is
Ukrainian. Two other entries had the same problem. They were unreachable by luck
rather than design. The fix included a test asserting that table never overlaps
the real language-code list — a bug in data is harder to spot than a bug in
logic, because it reads as knowledge.

**Attacking its own work beat asking for features.** "What are the
shortcomings?" produced placeholder *order* going unchecked, `50% off` read as a
type clash, and a class of bug no per-string rule could see — a source string
reworded with its translations left behind.

## Where it saved real time

Boilerplate, `rich` layout, and breadth of test cases. 270 tests exist because
the twentieth hostile input is nearly free; by hand I would have written five and
moved on. The judgement calls — what counts as a blocker, what to ignore, when to
stop adding checks — were mine, and they are what I would defend.
