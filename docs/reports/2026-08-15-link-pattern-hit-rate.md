# Link Pattern Hit Rate

**Source:** hosted instance snapshot 2026-08-15 (~1644 statements) — 1644 statements, 1829 links

## Reading the result

The headline is 120 of 1829 existing links (6.6%): that is the share whose link
type a cue in the source statement's own text would have proposed. Three types
carry real signal — `configures` 63/131 (48.1%), `composes` 25/62 (40.3%) and
`restricts` 16/54 (29.6%) — and inside them a few patterns are precise at the
statement level, notably `configures-capability` (26 of the 29 statements it
fires on have an outgoing `configures` link), `restricts-state` (5/6) and
`restricts-limits` (2/2). The four largest types in the substrate carry almost
nothing: `contains` 0/487, `triggers` 3/331, `requires` 0/170 and `governed-by`
0/104, and `accepts` 0/86, `cases` 0/50 and `varies-by` 0/22 are flat zero — in
this substrate those relations live on the edge, not in the source statement's
words. Shared-entity mention is not usable as a target selector on its own:
47634 pair fires produce 47561 false ones (99.8%), no link type falls below
99.4% false, and 10 of the 15 types with any pair fires are 100% false. Of the
64 patterns scored, 36 fire at least once and 6 more target link types with no
links in this snapshot at all, so they carry no ground truth here.

## Totals

| Statements | Links | Links in vocabulary | Hits | Links outside vocabulary |
| ---: | ---: | ---: | ---: | ---: |
| 1644 | 1829 | 1829 | 120/1829 (6.6%) | 0 |

## By link type

| Link type | Link hits | Pair fires | False fires |
| --- | ---: | ---: | ---: |
| contains | 0/487 (0.0%) | 722 | 722/722 (100.0%) |
| triggers | 3/331 (0.9%) | 1280 | 1280/1280 (100.0%) |
| requires | 0/170 (0.0%) | 3273 | 3273/3273 (100.0%) |
| configures | 63/131 (48.1%) | 10979 | 10941/10979 (99.7%) |
| enables | 6/114 (5.3%) | 11042 | 11038/11042 (100.0%) |
| proceeds | 5/109 (4.6%) | 1643 | 1642/1643 (99.9%) |
| governed-by | 0/104 (0.0%) | 0 | 0/0 (n/a) |
| accepts | 0/86 (0.0%) | 258 | 258/258 (100.0%) |
| establishes | 2/81 (2.5%) | 233 | 233/233 (100.0%) |
| composes | 25/62 (40.3%) | 3096 | 3078/3096 (99.4%) |
| restricts | 16/54 (29.6%) | 3936 | 3924/3936 (99.7%) |
| cases | 0/50 (0.0%) | 4497 | 4497/4497 (100.0%) |
| varies-by | 0/22 (0.0%) | 1029 | 1029/1029 (100.0%) |
| valued-by | 0/11 (0.0%) | 2353 | 2353/2353 (100.0%) |
| fallback-to | 0/9 (0.0%) | 1705 | 1705/1705 (100.0%) |
| replaces | 0/6 (0.0%) | 1588 | 1588/1588 (100.0%) |
| confirms | 0/2 (0.0%) | 0 | 0/0 (n/a) |

## By kind

| Kind | Link hits |
| --- | ---: |
| capability | 56/248 (22.6%) |
| event | 10/770 (1.3%) |
| property | 0/16 (0.0%) |
| rule | 35/161 (21.7%) |
| state | 19/634 (3.0%) |

## By kind × link type

| Kind | Link type | Link hits |
| --- | --- | ---: |
| capability | accepts | 0/4 (0.0%) |
| capability | composes | 0/1 (0.0%) |
| capability | configures | 55/75 (73.3%) |
| capability | contains | 0/31 (0.0%) |
| capability | enables | 0/33 (0.0%) |
| capability | fallback-to | 0/1 (0.0%) |
| capability | governed-by | 0/60 (0.0%) |
| capability | requires | 0/23 (0.0%) |
| capability | restricts | 1/3 (33.3%) |
| capability | triggers | 0/17 (0.0%) |
| event | accepts | 0/29 (0.0%) |
| event | cases | 0/5 (0.0%) |
| event | confirms | 0/2 (0.0%) |
| event | contains | 0/121 (0.0%) |
| event | enables | 0/34 (0.0%) |
| event | establishes | 2/61 (3.3%) |
| event | governed-by | 0/15 (0.0%) |
| event | proceeds | 5/106 (4.7%) |
| event | replaces | 0/1 (0.0%) |
| event | requires | 0/70 (0.0%) |
| event | restricts | 0/1 (0.0%) |
| event | triggers | 3/308 (1.0%) |
| event | varies-by | 0/17 (0.0%) |
| property | configures | 0/1 (0.0%) |
| property | fallback-to | 0/2 (0.0%) |
| property | governed-by | 0/2 (0.0%) |
| property | valued-by | 0/11 (0.0%) |
| rule | cases | 0/45 (0.0%) |
| rule | composes | 25/58 (43.1%) |
| rule | configures | 0/2 (0.0%) |
| rule | contains | 0/2 (0.0%) |
| rule | enables | 0/2 (0.0%) |
| rule | establishes | 0/1 (0.0%) |
| rule | fallback-to | 0/5 (0.0%) |
| rule | governed-by | 0/7 (0.0%) |
| rule | replaces | 0/3 (0.0%) |
| rule | requires | 0/11 (0.0%) |
| rule | restricts | 10/21 (47.6%) |
| rule | varies-by | 0/4 (0.0%) |
| state | accepts | 0/53 (0.0%) |
| state | composes | 0/3 (0.0%) |
| state | configures | 8/53 (15.1%) |
| state | contains | 0/333 (0.0%) |
| state | enables | 6/45 (13.3%) |
| state | establishes | 0/19 (0.0%) |
| state | fallback-to | 0/1 (0.0%) |
| state | governed-by | 0/20 (0.0%) |
| state | proceeds | 0/3 (0.0%) |
| state | replaces | 0/2 (0.0%) |
| state | requires | 0/66 (0.0%) |
| state | restricts | 5/29 (17.2%) |
| state | triggers | 0/6 (0.0%) |
| state | varies-by | 0/1 (0.0%) |

## By pattern

| Pattern | Link type | Statement precision | Link hits | Pair fires | False fires |
| --- | --- | ---: | ---: | ---: | ---: |
| accepts-may-provide | accepts | 0/2 (0.0%) | 0 | 258 | 258/258 (100.0%) |
| accepts-optional | accepts | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| accepts-verb | accepts | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| cases-level-for | cases | 0/19 (0.0%) | 0 | 4485 | 4485/4485 (100.0%) |
| cases-one-of | cases | 0/1 (0.0%) | 0 | 12 | 12/12 (100.0%) |
| cases-enumeration | cases | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| composes-formula | composes | 6/12 (50.0%) | 21 | 468 | 453/468 (96.8%) |
| composes-determined-by | composes | 3/11 (27.3%) | 4 | 1720 | 1717/1720 (99.8%) |
| composes-combines | composes | 2/9 (22.2%) | 9 | 1066 | 1059/1066 (99.3%) |
| configures-capability | configures | 26/29 (89.7%) | 55 | 2926 | 2892/2926 (98.8%) |
| configures-configured-on | configures | 33/86 (38.4%) | 63 | 10979 | 10941/10979 (99.7%) |
| configures-parameterises | configures | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| configures-verb | configures | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| confirms-if | confirms | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| contains-verb | contains | 0/5 (0.0%) | 0 | 722 | 722/722 (100.0%) |
| contains-composed-of | contains | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| contains-consists-of | contains | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| enables-state | enables | 6/56 (10.7%) | 6 | 10886 | 10882/10886 (100.0%) |
| enables-allows | enables | 0/1 (0.0%) | 0 | 145 | 145/145 (100.0%) |
| enables-verb | enables | 0/1 (0.0%) | 0 | 11 | 11/11 (100.0%) |
| enables-makes-available | enables | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| establishes-event-state | establishes | 1/2 (50.0%) | 2 | 233 | 233/233 (100.0%) |
| establishes-becomes | establishes | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| establishes-marks | establishes | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| establishes-moves-into | establishes | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| establishes-verb | establishes | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| fallback-to-defaults | fallback-to | 0/7 (0.0%) | 0 | 572 | 572/572 (100.0%) |
| fallback-to-verb | fallback-to | 0/6 (0.0%) | 0 | 1133 | 1133/1133 (100.0%) |
| fallback-to-none-apply | fallback-to | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| governed-by-capability | governed-by | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| governed-by-phrase | governed-by | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| proceeds-then | proceeds | 1/2 (50.0%) | 1 | 233 | 233/233 (100.0%) |
| proceeds-redirected | proceeds | 3/9 (33.3%) | 4 | 1410 | 1409/1410 (99.9%) |
| proceeds-followed-by | proceeds | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| proceeds-verb | proceeds | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| replaces-instead-of | replaces | 0/1 (0.0%) | 0 | 155 | 155/155 (100.0%) |
| replaces-verb | replaces | 0/11 (0.0%) | 0 | 1433 | 1433/1433 (100.0%) |
| requires-applies-when | requires | 0/2 (0.0%) | 0 | 367 | 367/367 (100.0%) |
| requires-on-condition | requires | 0/15 (0.0%) | 0 | 1702 | 1702/1702 (100.0%) |
| requires-only-when | requires | 0/2 (0.0%) | 0 | 584 | 584/584 (100.0%) |
| requires-verb | requires | 0/3 (0.0%) | 0 | 620 | 620/620 (100.0%) |
| requires-capability | requires | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| requires-must-have | requires | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| requires-needs | requires | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| requires-required | requires | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| restricts-limits | restricts | 2/2 (100.0%) | 8 | 332 | 324/332 (97.6%) |
| restricts-state | restricts | 5/6 (83.3%) | 5 | 968 | 966/968 (99.8%) |
| restricts-blocks | restricts | 1/3 (33.3%) | 1 | 835 | 834/835 (99.9%) |
| restricts-limited-to | restricts | 2/9 (22.2%) | 2 | 243 | 242/243 (99.6%) |
| restricts-bounds | restricts | 2/13 (15.4%) | 2 | 1679 | 1678/1679 (99.9%) |
| restricts-capability | restricts | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| restricts-verb | restricts | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| triggers-verb | triggers | 1/11 (9.1%) | 3 | 509 | 509/509 (100.0%) |
| triggers-produces | triggers | 0/5 (0.0%) | 0 | 371 | 371/371 (100.0%) |
| triggers-queues | triggers | 0/5 (0.0%) | 0 | 400 | 400/400 (100.0%) |
| triggers-causes | triggers | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| triggers-notifies | triggers | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| valued-by-derived | valued-by | 0/4 (0.0%) | 0 | 245 | 245/245 (100.0%) |
| valued-by-determined | valued-by | 0/11 (0.0%) | 0 | 1720 | 1720/1720 (100.0%) |
| valued-by-equals | valued-by | 0/9 (0.0%) | 0 | 388 | 388/388 (100.0%) |
| valued-by-state | valued-by | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |
| varies-by-capability | varies-by | 0/2 (0.0%) | 0 | 397 | 397/397 (100.0%) |
| varies-by-depends | varies-by | 0/4 (0.0%) | 0 | 632 | 632/632 (100.0%) |
| varies-by-verb | varies-by | 0/0 (n/a) | 0 | 0 | 0/0 (n/a) |

## Patterns outside vocabulary

- `performs-verb`
- `resolves-fix`
- `supersedes-verb`
- `teaches-how-to`
- `verifies-verb`
- `violates-missing`

## How to read

A **hit** is an existing link whose type is proposed by a cue in its source statement. The target does not affect hit detection.

A **pair fire** is a unique source, candidate, and link-type triple where the source has that cue and both statements mention at least one shared entity. It is true when the exact directed link exists and false otherwise. Statements without mentions produce no pairs.

**Statement precision** is the fraction of statements matched by a pattern that have at least one outgoing link of that pattern's type, regardless of target. Vocabulary types with zero links have no ground truth rather than a zero-percent hit rate.
