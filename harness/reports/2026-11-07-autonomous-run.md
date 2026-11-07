# The autonomous run of 2026-11-07 (handoff 5)

For Gabriel. Two Claude Code sessions ran it in parallel and split the work
on the morning of 2026-11-07, before either touched a shared file. Session
**projects-3e**, the one from handoffs 1-4, had already started task 35 under
your authorisation on PR #205, so it kept **T1**. Session **projects-4c**
(this report's author) took **T2-T7**. Every step either one took without
asking you is in `harness/AUTONOMY_LOG.md`, with the reason.

## 1. What was done

| Task | What | Links | State |
| --- | --- | --- | --- |
| T1 | Window selection by covariate balance (task 35), decision 0008 | draft #205, #207; issue #206; build #212; run [42366460941](https://github.com/gabrielsgaspar/research-terrain/actions/runs/42366460941); record, lessons, idea status and decision 0008 #219 | merged; window **0.25%**; decision 0008 accepted by rule |
| T2 | Identifier rule in `AGENTS.md`; scan of committed files for CPFs and voter IDs | #208 | merged; scan clean |
| T3 | Ideas 0003 (mayoral close races) and 0004 (alignment with the mayor); swing-voter line in idea 0001 | #209 | merged |
| T3 | Party-lineage table, as a proposal only | #213 (draft PR) | **open, not merged** (protected path) |
| T4 | Municipality-level power of close mayoral races (idea 0003) | draft #211, issue #214, build #216, run [42367009833](https://github.com/gabrielsgaspar/research-terrain/actions/runs/42367009833), record #217, lessons and status #218 | merged |
| T5 | Harness lesson on post-build tests; 2026-11-06 lessons tidy; README status | #210, and #220 (after 0008) | merged |
| T6 | Drafts of "What it doesn't do" and "Relevance to us" in the six literature notes | #215 | merged; marked as drafts |
| T7 | Pre-analysis plan draft, `harness/drafts/pap-draft.md` | #220 | merged; marked draft, nothing registered |
| — | This report | #221 | merged on CI |

## 2. Results

### T1: which close-race window is balanced

**Numbers.** Session projects-3e ran this (run 42366460941, record
`research/explore-runs/0001/42366460941.md`). It covered seven windows, ten
pre-election covariates, 2,000 re-flips and elections 2008-2024 pooled on the
exploration half. The omnibus balance p is **0.191 at 0.10%, 0.548 at
0.25%, 0.119 at 0.50%**, and 0.0005 (the floor) from 0.75% up. The rule you
fixed in issue #206 picks the widest window at or above 0.15 with every
narrower one also passing, which is **0.25%**. That window has 2,869 pairs
(2,328 in 2008-2020) against 4,575 at 0.50%. Pairs per window match the
feasibility census exactly, in every election, at 0.25%, 0.50%, 1% and 2%.
The covariate that fails is incumbency. Narrow winners had held the seat
before more often than narrow losers: by 1.1, 2.0 and 2.3 points at 0.10%,
0.25% and 0.50% (RI p 0.53, 0.084, 0.014), and by 6.4 points at 2%. Power
at 8% (2008-2020) falls from 0.944 / 0.797 / 0.448 at 0.50% to **0.868
(direct), 0.622 (displacement) and 0.307 (split)** at 0.25%. At 0.25% and 5
km there are 280 indigenous-side and 1,257 settlement-side candidates
(2008-2020).

**What it means.** The 0.50% window behind the 2026-11-06 results is not
balanced, so those results stand as pre-specified but carry a caveat: the
contrast partly mixes winning the seat with having held it. Their nulls are
not overturned. The confirmation half will use 0.25%, and that costs power.
Only the direct effect stays near 80%. On a half of the same size,
displacement and the constituency split would almost surely read "cannot be
applied at 80% power".

**Limits.** At 0.25% the incumbency gap (+2.0 points) is almost the 0.50%
gap. 0.25% passes mainly because fewer pairs make the test less able to see
the gap, not because the gap is gone. The balance pools 2008-2024, while
task B used 2008-2020. Power uses pre-election clearing only. Nothing was
re-estimated at 0.25% on post-election outcomes, because no merged issue
specifies that (hard stop 2). The reviewer's three nice-to-haves on #212
were not acted on, because none changes the result and a push would have
tripped the review guard.

### T4: close mayoral races are far too few (idea 0003)

**Numbers.** On the exploration half, 2008-2020, there are 45, 80 and 157
close mayoral races at 0.5%, 1% and 2% (deciding round; 1 of the 157 at 2%
went to a run-off). With one observation per race and pre-election clearing
as the outcome, power at decision 0007's 8% is **4.4%, 5.2% and 7.2%**. The
smallest effect detectable with 80% power is **89%, 67% and 45% of baseline
clearing**. The counts match what was expected (about half of the 91, 162
and 310 Legal Amazon races found by scoping).

**What it means.** A municipality-level design on mayoral close races could
only see effects of about half of all baseline clearing, which is
implausible for one election. The drafted kill criterion 1 of idea 0003
(power below 0.50 at every window) is met.

**Limits.** This is the best case for a race-level contrast (an attribute
that splits races 50/50), measured on pre-election clearing. A turf design
compares cells within the same municipality and would do better, but it
rests on the same 157 races. Scaling idea 0001's direct MDE (6.3% with
3,684 pairs) by √(3,684 / 157) gives roughly 30%. That is a rough guide, not
a computation. Idea 0003 stays `proposed` because its kill criteria are only
drafts.

### T2: no identifier is committed

No committed file under `data/fixtures/`, `research/`, `explore/` or
`paper/` holds a CPF or voter ID number. The fixtures' CPF and voter-ID
columns are zero-padded row numbers (CPF is `-4` in 2024). No 11- or 12-digit
number in those folders passes a CPF or voter-ID check-digit test, except
run ID 42193625417, which passes the CPF test by chance. No values were
printed during the scan.

## 3. Decisions taken by rule, judgement calls, and stops

**Decisions accepted by rule:** **Decision 0008, the close-race window: 0.25%.**
Its outcome follows mechanically from the rule written into issue #206
before the run (handoff 5 names it as the example of a decision that may be
accepted by rule). Its Accepted section reads "Accepted by rule (Claude
Code, autonomous run); Gabriel to review". No other decision was accepted.
Kill criterion 1 of idea 0001 still names 0.5% and was not edited. Idea
0001 stays `exploring`.

**Judgement calls you may want to check:**

- **Referee R5 "Not applicable" read as OK.** On #216 the referee marked R5
  (plausible magnitudes) "Not applicable", because no real run existed at
  build time. Handoff 5 says "every referee row R1-R7 is OK". I merged,
  reading N/A as "no referee problem", as on PRs #191 and #196, which you
  merged with the same R5 status. Recorded in the log.
- **Idea 0003's run-off counts** come from projects-3e's profiling of the
  raw TSE files (run-off ids `main + 1`; 2016+ votes only from `Válido`
  rows). The run confirmed them: no mayoral round-2 rows under other ids
  except four in 2020 (Macapá's postponed election).
- **Ideas table:** idea 0001's row said "proposed"; it has been "exploring"
  since 2026-11-03, so I corrected it in #209.
- **Idea 0003's status** is not changed to dead even though its drafted kill
  criterion 1 is met, because you have not confirmed its kill criteria.
- **Party-lineage table** (#213) was drafted from memory and is unverified;
  every row needs checking against the TSE files.

**Stops hit:** **None.** 0.10% passed (no "no window" stop), the window
counts and the idea 0003 counts matched what was expected, every merged PR
passed CI, and no agent PR needed a fix round. No file under `sealed/` or
`confirm/` was read, and no post-election outcome was analysed. No
identifier was committed or printed. The incumbency rebuild links
candidates by voter ID in memory only, and nothing hashed was stored, so
`ID_SALT` was not needed. Nothing touched permissions, secrets, workflows or
rulesets.

## 4. What needs you now

In rough order of importance. Each has a recommendation.

1. **Decision 0008 (window 0.25%).** Confirm it, or change the rule. Any
   change supersedes the decision; it is not an edit. *Recommendation:
   confirm.* You fixed the rule before seeing any balance, and changing it
   now that the power cost is known would be a forking path.
2. **Whether to spend the confirmation half on idea 0001 now.** (a) Register
   the PAP draft at 0.25%; (b) hold it while idea 0004 is scoped on the
   exploration half; (c) keep it for another idea. *Recommendation: (b).*
   The direct test would have about 0.87 power, but displacement and the
   split would not reach 80%, and the exploration half already points to a
   null. A count of aligned pairs for 0004 is cheap and uses no outcome.
3. **Kill criterion 3 in the PAP** (draft section 6): (i) keep as written,
   with expected power about 0.31, or (ii) make the split secondary.
   *Recommendation: (ii).* Also decide whether kill criterion 4's
   displacement branch (power 0.62) is treated the same way.
4. **PAP open choices** (draft sections 3-5 and 8). A: compute power on the
   confirmation half's pre-period (*recommended*) or carry it over. B: add
   incumbency as a secondary control line (*recommended*). C: report a
   failing confirmation-half balance test rather than stop (*recommended*).
   Also: read "0.5%" in kill criterion 1 as "the registered window"
   (*recommended*, through a superseding decision, since accepted criteria
   are not edited).
5. **Idea 0003 (mayoral close races).** Confirm its drafted kill criteria
   and mark it dead. *Recommendation: yes.* Power is 4-7% at 8%.
6. **Idea 0004 (alignment with the mayor).** Confirm its drafted kill
   criteria. Next step: a count of aligned and unaligned pairs at 0.25%
   (same election, no lineage needed). *Recommendation: let me draft it as
   task 37.* Note that the 200-pair bar of its first kill criterion now
   applies at 0.25%.
7. **Party-lineage table, PR #213 (draft).** It was drafted from memory and
   is unverified. *Recommendation: leave it open.* Same-election alignment
   does not need it. Check it against the TSE files only if 0004 goes
   across elections.
8. **Literature-note drafts (#215).** Rewrite the "What it doesn't do" and
   "Relevance to us" sections in your words. *Recommendation: start with
   Borusyak et al. and Fiva et al.*, the two the design leans on most.
9. **Referee R5 "Not applicable."** This run and task 35 read it as no
   problem (#212, #216). *Recommendation: confirm*, and say so in the next
   handoff, or have the referee mark R5 OK when no numbers exist.
