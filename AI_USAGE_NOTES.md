# Scaffold + evidence for AI_USAGE.md

Working notes. Write `AI_USAGE.md` from this, then delete this file.

Aim for ~1 page. Prefer three specific moments over ten vague ones — the brief
asks for "two or three", and a named example with a reason beats a list.

---

## 1. What I used it for  *(~4 lines)*

Prompts:
- Which parts did you hand over, and which did you keep?
- What direction did you set before any code existed?

Evidence you have:
- `thoughts.txt` was written **before** you started, and names the constraint
  that drove the whole design: *"Do NOT oveflag issues, if anything I'd rather
  the tool showed me the most egregious problems."*
- Also from before you started: *"Asked Claude to explain it to me again so I
  know I understood it."* — you used it to check comprehension before building.
- You chose: Python, CLI, "pretty and colorful", severity tiers, and the shape of
  the output.

---

## 2. Two or three things it gave me that I kept  *(~3 short paragraphs)*

Prompts for each: what was it, why did you keep it, and how did you satisfy
yourself it was right rather than just plausible?

Candidates — pick the ones you actually understand well enough to defend:

**(a) The regression classifier.** Your opening position was *"as of right now i
think a diff tool would suffice just to start somewhere."* The pushback was that
the diff is the engine, not the product, and that running each rule against
**both** files makes the same problem read as regression / pre-existing / fixed.
That is `engine._classify`, and it is why the French `% ...` → `%u...` case
reports as a fix rather than a risk — the trap the brief plants.
*If you use this one, be ready to draw the three-row table.*

**(b) `jp` should be `ja`.** The new Japanese strings are filed under the ISO 3166
country code for Japan; the language code is `ja`. Complete, correct translations
reaching zero players, invisible to a diff and to English-language QA. You did
not find this and would not have.

**(c) Line numbers from a second parse.** `plistlib` discards positions, so
`locate.py` re-parses with `expat` purely to build a line index. What turns "the
Russian string is broken" into `:22`.

---

## 3. Two or three things I rejected or sent back  *(~3 short paragraphs)*

This section is the strongest evidence you have. Every item below started with
you, not me.

**(a) The first CLI output — your biggest correction.** Your words: *"all i see
is that some things were flagged, ideally id like to see what and where so i can
fix it."* Everything in the detail cards — file, line, the `en-US` source, the
highlighted characters, the imperative fix — exists because you sent it back.
This is what your note *"ai did not do a great job at making this human
friendly"* refers to. Say so plainly.

**(b) Register.** *"dont write 'file name says' whatevere, this is a tool
supposed to be used by coworkers."* Chasing that found a worse one underneath:
language codes were being interpolated as bare words, so with `lang="it"` the
report said *"it players see blank space here"* — which parses as the pronoun.
Codes are quoted now. Worth noting the pattern: a tone complaint uncovered a
grammar bug that had been in every run.

**(c) An honesty problem.** *"instead of saying 'live' call it older version,
because we dont know for sure if its live."* The README **listed** "the
second-newest file is live" as an assumption, and the output **stated it as
fact**. The tool knows which file is older; it cannot know what production is
serving.

**(d) A self-contradicting prompt.** *"remove the 'press "." or any key' it
doesnt make sense."* It named a key and then said the key did not matter.

**(e) The console-width fix that broke something else.** You asked for the text
to fit the window; it added a `mode con` resize, which pins the console *buffer*,
so maximising left the report boxed into the left 120 columns. *"the bat gets
weird becasue if you full screen it."*

---

## 4. How I verified it  *(~4 bullets)*

Prompts: what did you refuse to take on trust, and what did you make it prove?

Evidence:
- You asked it to attack its own work rather than add features: *"are there any
  shorrtcomings, edge cases that i or u not seeing?"* and *"this should be as
  robust as possible, i do not want to erode trust."* That produced the
  false-positive corpus and found placeholder *order* going unchecked.
- You ran it yourself and found what testing did not — see section 5.
- Claims about the files were checked against the files rather than asserted.
- Subtle fixes got a test named after the bug so they cannot come back quietly.

---

## 5. What surprised me  *(~3 short paragraphs — the most valuable section)*

The honest through-line: **the AI's failures were confident, and using the tool
caught more than testing it did.**

**(a) It wrote a launcher that lied about the result.** The `.bat` called `py -3`,
sent its errors to `nul`, and reported the exit code as a verdict. On this machine
`py -3` is a different Python from the one with the package installed, so the tool
never ran — and the window said *"Blockers found. Do not ship yet."* A confident
verdict for a run that never happened, in a tool whose entire purpose is
trustworthy output.

**(b) Its reference data was wrong.** It built a table of country codes mistaken
for language codes and listed `uk` as *"United Kingdom, use `en`"*. `uk` is
Ukrainian. Two other entries had the same problem. A bug in data is harder to
spot than a bug in logic, because it reads as knowledge.

**(c) Its own audit script was wrong.** Asked to check the findings against the
data, it wrote a script that reported zero line breaks in every string and
appeared to contradict the tool. The script was broken, not the tool. Verification
needs verifying.

**(d) Using it beat testing it.** Nearly every real bug in the second half came
from you poking at it, not from the test suite:
- *"what if there are multiple files ... like 10, what would happen?"* → found
  that a `gameconfig_9_0_0.plist` in the folder outranked the real candidate, so
  the tool would have confidently compared two unrelated files.
- *"i tried comparing versions and chose '2 1' instead of '1 2' and i see weird
  things"* → the analysis was right but every finding read backwards; rollback is
  now a direction the report understands.
- *"i cant see the versions being compared without scrolling"* → the summary was
  31 lines and a double-clicked console is 30.

Every automated test ran the comparison forwards, in a clean folder, at a width
nobody uses.

---

## 6. Scale and time  *(~3 lines — worth adding, not asked for)*

The brief allows ~5 hours and asks you to use AI. The result is ~2,600 lines of
tool and ~1,900 of tests, which is not five hours of typing — it is five hours of
directing, correcting and checking. Say that plainly rather than leaving a
reviewer to wonder. Then say what the five hours actually went on: the judgement
calls. What counts as a blocker, what to ignore, when to stop adding checks.

---

## Things to be careful about

- Do not claim to have found something you did not. The `jp`/`ja` catch was the
  AI's; saying so is more convincing than the alternative.
- Do not overclaim understanding either. Anything you list as "kept" you should
  be able to explain at a whiteboard — pick accordingly.
- The false-positive story is your best single anecdote if you want one: the
  number check flagged the Turkish pool rules, which write "Rack 1"/"Rack 2" as
  *İlk üçgen*/*İkinci üçgen*. A correct translation reported as broken. Numbers
  below ten are ignored now, and there is a test named for it.
