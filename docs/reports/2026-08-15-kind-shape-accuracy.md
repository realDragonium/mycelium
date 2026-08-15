# Kind Shape Classification Accuracy

**Source:** production snapshot 2026-08-15 — 1644 statements

## Totals

| Statements | Assigned | Correct | Wrong | Ambiguous | Unmatched | Precision | Recall | Flag rate |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1644 | 1117 | 1077 | 40 | 1 | 526 | 1077/1117 (96.4%) | 1077/1644 (65.5%) | 527/1644 (32.1%) |

## By true kind

| Kind | n | Correct | Misassigned | Ambiguous | Unmatched | Recall | Flag rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| event | 531 | 350 | 17 | 0 | 164 | 350/531 (65.9%) | 164/531 (30.9%) |
| state | 567 | 323 | 11 | 0 | 233 | 323/567 (57.0%) | 233/567 (41.1%) |
| capability | 197 | 192 | 1 | 0 | 4 | 192/197 (97.5%) | 4/197 (2.0%) |
| rule | 213 | 104 | 9 | 1 | 99 | 104/213 (48.8%) | 100/213 (46.9%) |
| property | 136 | 108 | 2 | 0 | 26 | 108/136 (79.4%) | 26/136 (19.1%) |
| procedure | 0 | 0 | 0 | 0 | 0 | n/a | n/a |
| action | 0 | 0 | 0 | 0 | 0 | n/a | n/a |
| check | 0 | 0 | 0 | 0 | 0 | n/a | n/a |

## Precision by assigned kind

| Assigned kind | Assigned | Correct | Wrong | Precision |
| --- | ---: | ---: | ---: | ---: |
| event | 361 | 350 | 11 | 350/361 (97.0%) |
| state | 345 | 323 | 22 | 323/345 (93.6%) |
| capability | 193 | 192 | 1 | 192/193 (99.5%) |
| rule | 110 | 104 | 6 | 104/110 (94.5%) |
| property | 108 | 108 | 0 | 108/108 (100.0%) |
| procedure | 0 | 0 | 0 | n/a |
| action | 0 | 0 | 0 | n/a |
| check | 0 | 0 | 0 | n/a |

## Confusion matrix

| True kind | event | state | capability | rule | property | (ambiguous) | (unmatched) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| event | 350 | 14 | 0 | 3 | 0 | 0 | 164 |
| state | 9 | 323 | 0 | 2 | 0 | 0 | 233 |
| capability | 0 | 1 | 192 | 0 | 0 | 0 | 4 |
| rule | 1 | 7 | 1 | 104 | 0 | 1 | 99 |
| property | 1 | 0 | 0 | 1 | 108 | 0 | 26 |
| procedure | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| action | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| check | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## By shape

| Shape | Kind | Fires | Correct | Precision |
| --- | --- | ---: | ---: | ---: |
| capability-modal | capability | 193 | 192 | 192/193 (99.5%) |
| event-passive | event | 332 | 322 | 322/332 (97.0%) |
| event-active | event | 29 | 28 | 28/29 (96.6%) |
| state-passive | state | 159 | 149 | 149/159 (93.7%) |
| state-perfect | state | 3 | 3 | 3/3 (100.0%) |
| state-copula-condition | state | 103 | 93 | 93/103 (90.3%) |
| state-possession | state | 35 | 33 | 33/35 (94.3%) |
| state-stative-verb | state | 32 | 31 | 31/32 (96.9%) |
| state-negated-np | state | 14 | 14 | 14/14 (100.0%) |
| rule-passive | rule | 37 | 36 | 36/37 (97.3%) |
| rule-formula | rule | 73 | 69 | 69/73 (94.5%) |
| rule-band | rule | 21 | 20 | 20/21 (95.2%) |
| rule-measure | rule | 5 | 5 | 5/5 (100.0%) |
| property-noun-phrase | property | 108 | 108 | 108/108 (100.0%) |
| action-imperative | action | 0 | 0 | n/a |
| check-imperative | check | 0 | 0 | n/a |
| procedure-how-to | procedure | 0 | 0 | n/a |

## Floor

Precision of an assigned kind must reach 90%. A kind the classifier never assigned has nothing to measure.

- `event`: met — 350/361 (97.0%) precision
- `state`: met — 323/345 (93.6%) precision
- `capability`: met — 192/193 (99.5%) precision
- `rule`: met — 104/110 (94.5%) precision
- `property`: met — 108/108 (100.0%) precision
- `procedure`: never assigned in this snapshot
- `action`: never assigned in this snapshot
- `check`: never assigned in this snapshot

## Reading the result

Every kind the classifier actually assigns clears the 90% precision floor, and
it does so by refusing to guess: 527 of 1644 statements (32.1%) come back
flagged rather than assigned. That trade is deliberate. The `X is <participle>`
surface carries 455 events, 266 states and 69 rules in this snapshot, so no
single passive shape can separate them; instead three disjoint participle
allow-lists fire, and a participle in none of them leaves the fragment
unmatched. Vocabulary the lists have never seen therefore costs recall, never
precision.

Recall varies by how formulaic a kind is. Capability is nearly free — 192 of 197
statements carry a modal — while rule sits at 48.8%, because roughly half the
rules here are ordinary copulas whose only rule signal is semantic rather than
lexical. State's 41.1% flag rate is the same story from the other side. The 40
wrong assignments concentrate in two cells of the confusion matrix: events read
as states and states read as events, all of them passives whose participle sits
on the wrong list for that one sentence.

Fragments carrying two predicates — joined by a semicolon or by `and` — are
refused outright rather than classified by their first clause. That costs about
one point of recall on this snapshot and removes no errors from it, but it is
the honest contract: splitting a compound belongs to segmentation, and a
classifier that labels half a fragment is wrong in a way the numbers here would
not show.

Two caveats. The lexicons were authored with this snapshot's participle
frequencies in view, so precision here is optimistic for unseen vocabulary —
though the allow-list design means unfamiliar words flag instead of
misclassifying. And the three prescriptive kinds have no statements at all in
production, so `action-imperative`, `check-imperative` and `procedure-how-to`
are exercised only by unit tests; they are unmeasured, not zero.
