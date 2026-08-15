# Kind Shape Classification Accuracy

**Source:** production snapshot 2026-08-15 — 1644 statements

## Totals

| Statements | Assigned | Correct | Wrong | Ambiguous | Unmatched | Precision | Recall | Flag rate |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1644 | 1134 | 1094 | 40 | 1 | 509 | 1094/1134 (96.5%) | 1094/1644 (66.5%) | 510/1644 (31.0%) |

## By true kind

| Kind | n | Correct | Misassigned | Ambiguous | Unmatched | Recall | Flag rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| event | 531 | 355 | 17 | 0 | 159 | 355/531 (66.9%) | 159/531 (29.9%) |
| state | 567 | 330 | 11 | 0 | 226 | 330/567 (58.2%) | 226/567 (39.9%) |
| capability | 197 | 196 | 1 | 0 | 0 | 196/197 (99.5%) | 0/197 (0.0%) |
| rule | 213 | 105 | 9 | 1 | 98 | 105/213 (49.3%) | 99/213 (46.5%) |
| property | 136 | 108 | 2 | 0 | 26 | 108/136 (79.4%) | 26/136 (19.1%) |
| procedure | 0 | 0 | 0 | 0 | 0 | n/a | n/a |
| action | 0 | 0 | 0 | 0 | 0 | n/a | n/a |
| check | 0 | 0 | 0 | 0 | 0 | n/a | n/a |

## Precision by assigned kind

| Assigned kind | Assigned | Correct | Wrong | Precision |
| --- | ---: | ---: | ---: | ---: |
| event | 366 | 355 | 11 | 355/366 (97.0%) |
| state | 352 | 330 | 22 | 330/352 (93.8%) |
| capability | 197 | 196 | 1 | 196/197 (99.5%) |
| rule | 111 | 105 | 6 | 105/111 (94.6%) |
| property | 108 | 108 | 0 | 108/108 (100.0%) |
| procedure | 0 | 0 | 0 | n/a |
| action | 0 | 0 | 0 | n/a |
| check | 0 | 0 | 0 | n/a |

## Confusion matrix

| True kind | event | state | capability | rule | property | (ambiguous) | (unmatched) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| event | 355 | 14 | 0 | 3 | 0 | 0 | 159 |
| state | 9 | 330 | 0 | 2 | 0 | 0 | 226 |
| capability | 0 | 1 | 196 | 0 | 0 | 0 | 0 |
| rule | 1 | 7 | 1 | 105 | 0 | 1 | 98 |
| property | 1 | 0 | 0 | 1 | 108 | 0 | 26 |
| procedure | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| action | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| check | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## By shape

| Shape | Kind | Fires | Correct | Precision |
| --- | --- | ---: | ---: | ---: |
| capability-modal | capability | 197 | 196 | 196/197 (99.5%) |
| event-passive | event | 337 | 327 | 327/337 (97.0%) |
| event-active | event | 29 | 28 | 28/29 (96.6%) |
| state-passive | state | 165 | 155 | 155/165 (93.9%) |
| state-perfect | state | 4 | 4 | 4/4 (100.0%) |
| state-copula-condition | state | 103 | 93 | 93/103 (90.3%) |
| state-possession | state | 35 | 33 | 33/35 (94.3%) |
| state-stative-verb | state | 32 | 31 | 31/32 (96.9%) |
| state-negated-np | state | 14 | 14 | 14/14 (100.0%) |
| rule-passive | rule | 38 | 37 | 37/38 (97.4%) |
| rule-formula | rule | 74 | 70 | 70/74 (94.6%) |
| rule-band | rule | 21 | 20 | 20/21 (95.2%) |
| rule-measure | rule | 5 | 5 | 5/5 (100.0%) |
| property-noun-phrase | property | 108 | 108 | 108/108 (100.0%) |
| action-imperative | action | 0 | 0 | n/a |
| check-imperative | check | 0 | 0 | n/a |
| procedure-how-to | procedure | 0 | 0 | n/a |

## Floor

Precision of an assigned kind must reach 90%. A kind the classifier never assigned has nothing to measure.

- `event`: met — 355/366 (97.0%) precision
- `state`: met — 330/352 (93.8%) precision
- `capability`: met — 196/197 (99.5%) precision
- `rule`: met — 105/111 (94.6%) precision
- `property`: met — 108/108 (100.0%) precision
- `procedure`: never assigned in this snapshot
- `action`: never assigned in this snapshot
- `check`: never assigned in this snapshot

## Reading the result

Every kind the classifier actually assigns clears the 90% precision floor, and
it does so by refusing to guess: 510 of 1644 statements (31.0%) come back
flagged rather than assigned. That trade is deliberate. The `X is <participle>`
surface carries 455 events, 266 states and 69 rules in this snapshot, so no
single passive shape can separate them; instead three disjoint participle
allow-lists fire, and a participle in none of them leaves the fragment
unmatched. Vocabulary the lists have never seen therefore costs recall, never
precision.

Recall varies by how formulaic a kind is. Capability is nearly free — 196 of 197
statements carry a modal — while rule sits at 49.3%, because roughly half the
rules here are ordinary copulas whose only rule signal is semantic rather than
lexical. State's 39.9% flag rate is the same story from the other side. The 40
wrong assignments concentrate in two cells of the confusion matrix: 14 events
read as states and 9 states as events, all of them passives whose participle
sits on the wrong list for that one sentence.

Two caveats. The lexicons were authored with this snapshot's participle
frequencies in view, so precision here is optimistic for unseen vocabulary —
though the allow-list design means unfamiliar words flag instead of
misclassifying. And the three prescriptive kinds have no statements at all in
production, so `action-imperative`, `check-imperative` and `procedure-how-to`
are exercised only by unit tests; they are unmeasured, not zero.
