# Findings — `localisations_1_2_1.plist`

**Do not ship this as it stands.** Four blockers, three things to confirm, one
genuine fix. Reproduce with `locheck` in the project folder.

---

## Ship-blockers

### 1. Spanish is gone from the entire file

`es` was in all three live entries and is in none of the candidate's. Every
Spanish-speaking player loses every string in this file at once — the biggest
blast radius here by a wide margin.

If this was deliberate, it is a product decision that needs saying out loud. If
not, `es` needs restoring in `2b827952`, `7a794655` and `d8225439`.

### 2. Russian countdown lost its placeholder — line 22

```
en-US   Starting in %u...
live    До начала %u...
new     До начала %...
```

The `%` is now followed by `...`, which is not a valid format specifier. This is
the class of bug the brief calls out: depending on how the client formats it,
this crashes or renders garbage, and it is invisible in a line-by-line diff.

### 3. Italian countdown is empty — line 16

`<string></string>` where `Inizio tra %u...` used to be. Italian players see
blank space on a countdown.

### 4. Italian share text has an unclosed token — line 73

```
en-US   I just reached number 1 A:[in Country/in the world] B:[today/this week/all time]!
new     Ho appena raggiunto la posizione numero 1 B:[oggi/questa settimana/sempre!
```

One `[`, no `]`, and the `A:[...]` slot is missing entirely. The client will
render the raw markup to the player, or fail to substitute.

---

## Confirm before shipping

### 5. The version was never bumped — line 6

The file is named `1_2_1` but declares `<string>1.2.0</string>` — identical to
what is live. Depending on how the client and CDN key their caches, **this
release may never reach a single device.** Cheap to fix, easy to miss, and if it
ships this way the other four items are academic.

### 6. The new Japanese strings will reach nobody — line 83

The four new Japanese translations are filed under **`jp`**. That is the ISO 3166
country code for Japan. The language code is **`ja`**, which is what clients ask
for. The translations are complete and correct and no player will ever see one —
they will all fall back to English.

This is the one I would most want a second pair of eyes on, because nothing about
it looks wrong. It survives a diff, a spot check and a QA pass in English.

### 7. `7a794655` ("Play as Guest") was removed

Fine if intended. Worth confirming no shipped client build still requests it —
old app versions outlive content updates, and those players would see a blank
button.

---

## Lower priority, still real

- **`9bb069bc` / `pt-BR`, line 58** — says a **3 second** penalty where every
  other language says **30**. Not a crash; just a game rule that is wrong in
  Portuguese.
- **`1981dc5a` / `tk`, line 81** — offers two options where `en-US` offers three
  (`today / this week / all time`). The client selects by index.
- **`d8225439` / `jp`, line 45** — the reward text collapsed five lines into one.
  It will not wrap as the UI expects.

## Not a problem — worth saying so

**`2b827952` / `fr`, line 14** changed from `Commence dans % ...` to
`Commence dans %u...`. Its placeholders changed, which looks alarming, but the
live version was broken and the new one matches the source. **This is a fix.**
The tool reports it in green so nobody spends time on it.

Likewise, `d8225439` / `pt-BR` gained an accent (`videos` → `vídeos`). Changed,
not risky, not reported.

Also noted but **not** this release's problem: `tk` is the code for Turkmen and
those strings are plainly Turkish (`tr`). That is already live, so it is a ticket
rather than a blocker.

---

## How I would use this

**As a pre-merge check on the localisation repo.** `locheck old.plist new.plist`
exits `1` on blockers, so it fails a build with no wrapper. That is where it is
worth most — it puts the feedback on the person who made the change, while they
still remember why.

**Manually before release**, by whoever is shipping. `locheck` with no arguments
picks the two newest versions; the summary is a fifteen-second read and any key
expands it into per-finding detail with file, line and a fix.

**Not** as a gate on everything. Only blockers fail the build by default. HIGH
items are "confirm this was intentional" — a human call, not a machine one. If
that ever inverts, people will start passing `--no-verify`, and then it catches
nothing.

The one thing I would ask the team for: **a way to know a string will overflow
its button.** It is the failure the brief describes that I can only approximate,
and it needs component widths that live in the client, not in this file.
