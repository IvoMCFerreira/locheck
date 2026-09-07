# AI usage

I used Claude (Opus, inside Claude Code) for all of this. Not as something I
copied answers from. More like a fast pair who works quickly, sounds certain, and
needs checking.

## What I used it for

First I had it re-explain the brief in plain terms, to check I had read it the
way it was meant. Then to read the two plist files, write the tool, write the
tests, and later to attack its own work.

I set the direction before any code existed. Python, a CLI, severity levels, and
the rule I wrote in my notes before starting: do not overflag. I would rather it
showed me only the worst problems. That drove most of what followed.

## Three things it gave me that I kept

**The mechanism the verdicts rest on.** My notes from before any code existed say
the tool could not be too simple, or the problem would already be solved by
something off the shelf. So I was not looking for a diff. What I did not have yet
was the mechanism. It suggested running every check against both files rather
than against the new one alone, and that is the hinge the whole thing turns on:
the same problem then means three different things depending on the older file.
This release broke it, it was already broken, or this release fixed it. That is
the whole tool. It is why the French countdown, which changed from `% ...` to
`%u...`, comes out green as a fix instead of red as a risk. Severity without that
distinction is guesswork, and guessing on severity is the trap the brief warns
about.

**`jp` should be `ja`.** The new Japanese strings are filed under `jp`, the
country code for Japan. The language code is `ja`. So the translations are
finished, correct, and reach nobody. I did not find this and I doubt I would
have.

**Line numbers.** Python's plist parser throws away positions, so it wrote a
second small parser that does nothing but record which line each string is on.
Obvious once you see it. It is the difference between "the Russian string is
broken" and "line 22".

## Three things I sent back

**The first version of the output.** It told me things were flagged but not what
or where. No line numbers, nothing to act on. It ran fine and was useless. The
whole detail view exists because I sent it back: file and line, the English
source to compare against, the highlighted characters, and a line saying what to
do. This is what I meant in my notes about it not doing a great job of making
this human friendly.

**The way it wrote.** The report said "file name says 1.2.1", which reads like a
note to yourself, not a tool other people use. Fixing the wording turned up
something worse. Language codes were being dropped into sentences as plain words,
so with Italian it said "it players see blank space here". That had been in every
run and neither of us had noticed.

**Calling a file "live".** The tool described the older file as the live one. It
cannot know that. A version can be built and never shipped. The README even
listed it as an assumption while the output stated it as fact. It says older and
newer now.

## Making it something a person would want to use

Beyond that detail view, a lot of what I asked for had nothing to do with
correctness. A release check that is unpleasant to read gets skipped, and a check
that gets skipped catches nothing. My note after the first working version was
that it was verbose and gimmicky to use, and the line I kept coming back to was
this: make it work, make it pretty.

So the shape of the tool is mostly quality of life decisions I pushed for.

**It defaults to the summary.** The verdict and the table are what you need in
order to decide whether to ship. The detail sits behind one keypress, for when
you have already decided to fix something.

**It needs no arguments.** Run it in a folder and it works out which two versions
you meant, newest against the one before it. Nobody should have to type two paths
to do the obvious thing.

**Each problem is reported once, at its worst severity.** That has a cost I knew
about when I chose it, because a blocker can hide a smaller issue in the same
string. I took the trade anyway: a list nobody reads to the end catches nothing.

None of this came for free. It is the part it was weakest at unprompted, and the
part I spent the most time sending back.

## Built to be dropped into a pipeline

The other half of the direction was that this should not stay something you run
by hand on a laptop. My notes partway through: it will likely run on CI, it
should be integrated, and a release should fail if the checker finds blockers.
That is a constraint rather than a feature, and it decided several things.

**Exit codes carry the verdict.** 0 nothing blocking, 1 blockers, 2 files
unreadable. The gate is just running the tool, so there is no wrapper script and
nothing to parse.

**`--json` prints the whole report as data.** Partly for a pipeline to read, and
partly because it is the seam a web or mobile front end would sit on if this ever
grew one.

**A container image.** Pinned and self contained, with no Python needed on the
host, so a laptop and a build agent give the same answer. The README covers how
to run it, and `pyproject.toml` names the dependencies in one place instead of
leaving you to discover them by running the tool.

**A Makefile.** The handful of things you actually do with this are one word
each.

The workflow in `.github` applies the same idea to the repo itself. Any pull
request touching a plist runs the checker, and a separate job builds the
container image and checks that the exit codes survive the container boundary.

## How I checked it

I did not take its word for anything that mattered. I made it prove claims about
the files against the files. I asked it to attack its own work instead of adding
features, which is where the false positive tests came from, and where it found
it was not checking placeholder order at all. When a fix was subtle I asked for a
test named after the bug so it could not come back quietly. And I ran the tool
myself, a lot.

## What surprised me

**It wrote a launcher that lied.** The double-click file called one Python, hid
the error, and turned the exit code into a verdict. On my machine that Python did
not have the tool installed, so nothing ran, and the window said "Blockers found.
Do not ship yet." A confident answer to a question it never asked. In a tool that
exists to be trusted, that is the worst bug you can have.

**Its facts were wrong and looked right.** It wrote a list of country codes
people mistake for language codes and put `uk` on it as "United Kingdom, use en".
`uk` is Ukrainian. Two more entries had the same problem. Wrong data is harder to
catch than wrong code because it reads like knowledge.

**Using it found more than testing it.** Most of the real bugs in the second half
came from me poking at it, not from the tests. Asking what happens with ten files
in a folder found an unrelated config file being picked as the candidate.
Choosing the versions in the wrong order gave me a report where every finding
read backwards. Every test it wrote ran the comparison forwards, in a clean
folder, at a window size nobody uses.

## On the size of this

The brief allows around five hours and asks you to use AI. What came out is about
2,600 lines of tool and 1,900 of tests, which is not five hours of typing. It is
five hours of pointing it at things, sending work back, and checking what
mattered. The code was the fast part. The decisions were slow: what counts as a
blocker, what to ignore on purpose, and when to stop adding checks. Those are
mine and they are what I would defend.
