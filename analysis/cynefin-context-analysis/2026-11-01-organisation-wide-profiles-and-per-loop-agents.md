2026-11-01

# Cynefin Context Analysis: organisation-wide profiles and per-loop agents

## At a glance

Context: Complicated for the agent-selection model, Complex for how profiles are used in practice · confidence: moderate (repository evidence, no stakeholder input) · review point: after the first month of real Loop deliveries, or as soon as one Loop reports an analysis produced by the wrong profile

- The rules for who may work on a board are now explicit enough to analyse and test, so the next step there is ordinary engineering rather than experimentation (Complicated · observed · Context assessment).
- Which profile actually helps a discussion, and how often an organisation profile is worth its cost, cannot be predicted from the repository and should be discovered with a few bounded runs (Complex · inferred · Recommended response).
- The risk that matters most is a silently wrong agent running a Loop, so the immediate work is making the chosen agent visible in every run while the usage questions are still open (Complicated · observed · Evidence and perspectives).

## Decision or situation

Decision in scope: how agent profiles should be scoped and chosen in Tralala, now that the installation
has board profiles (Analytics agent and the discussion roles) and two organisation profiles
(Coordinator, Architect). Owner: the product owner of this repository. Affected: administrators who
configure profiles, people who run Loops, and the agents themselves, whose output quality depends on
the profile chosen. Time horizon: the current development phase, before any real user depends on it.

The outcome that matters: a person can tell which agent will do the work, trust that the rules prevent
a wrong profile from being used, and learn over time which profile is worth assigning where.

## Evidence and perspectives

Observations (this session):

- Board profiles and organisation profiles are separated by a `scope` on the role template, enforced
  in `AgentService.validate_ids` and covered by tests.
- Agent resolution has a defined precedence (explicit choice, then the Loop preference, then a board
  default), and every run snapshots the agent name and the role text it used.
- A gap remains: generation itself does not refuse an organisation profile when the board lists no
  agents (recorded in this round's FMEA as F2).
- The two new profiles were written from the owner's description, not from observed sessions with
  people using them.

Assumptions: the profiles will be used mostly inside discussions and overview requests; the owner
intends to run Loops with a local model first.

Unknowns: how often a Coordinator or Architect answer is actually better than a board profile's; how
much an organisation-wide repository token costs in tokens per request; whether people will maintain
per-Loop preferences or leave them empty.

Different perspectives: an administrator wants few choices and predictable defaults; a person running
a Loop wants the best answer, not the right taxonomy; an agent wants enough context to be useful, which
is exactly what the organisation profiles need and the board profiles must not have.

## Context assessment

**Agent selection rules: Complicated.** Cause and effect are knowable and testable (an organisation
profile must never run a Loop; a board lists the agents that may touch it; a stale preference falls
back). The response is analysis and expertise: define the rule once, test it, and keep the precedence
in one function. There is more than one sound design (per-board, per-Loop, per-purpose), which is why
it needed a decision record rather than a rule of thumb.

**Use of the new profiles: Complex.** Whether the Coordinator's recommendations improve routing, and
whether the Architect's whole-installation view is worth an organisation-wide token, will only be
visible after several real uses. There is no reliable way to derive it from the repository. Multiple
plausible outcomes exist (adopted, ignored, or actively confusing), and the pattern emerges from use.

**Not chaotic:** nothing is on fire, the system starts, and migrations are reversible by backup, so
urgent stabilization is not the right response. **Not disorder:** the disagreement about profile value
does not prevent the selection rules from being analysed; the two parts are separable, which is why
they are assessed apart.

Confidence: moderate. The rules assessment rests on code and tests (observed); the usage assessment is
inferred and would change quickly with real transcripts.

## Recommended response

1. **Treat the rule work as Complicated: finish and test it.** Close the generation gap (refuse an
   organisation profile where a Loop runs) and keep the precedence pinned by tests. Cheap, and it
   removes the failure mode that matters most. (Observed evidence; no experimentation needed.)
2. **Treat the profile value as Complex: run bounded probes.** Pick two or three real discussions and
   one cross-repository question; run them with the recommended profile and with the previous default;
   record which answer the person actually acted on. Bounds: existing boards, no new credentials
   beyond a read-only organisation token, and stop after the probes if the answers are indistinguishable.
3. **Amplify what works, dampen what does not.** If the Coordinator's routing is used, keep the
   recommendation in the discussion flow; if it is ignored, remove the prompt paragraph that promises
   routing rather than leaving a promise nothing fulfils.
4. **Keep the review point explicit:** revisit after the first month of real Loop deliveries, or
   sooner if a run reports an unexpected profile.

## Reassessment

Indicators that the rules part is solved: a run cannot be started with an organisation profile; a
stale preference is visible in the run record; the board dialog never offers a profile the server would
refuse.

Indicators for the usage part: a person follows the Coordinator's recommendation at least once; the
Architect's answer names a file or manifest someone then opens; the same questions keep being asked of
board profiles instead.

Conditions that would change the response: a stakeholder states that overview answers are the primary
product (then the organisation profiles deserve their own surface, not a discussion role), or a real
token incident (then the organisation-wide token becomes a Chaotic-then-Complicated problem, and the
first response is to revoke and narrow it).

## Open questions

- Who will judge whether an organisation profile's answer was worth the tokens, and where is that
  recorded?
- Does the intended first user run Loops with a local model, where a whole-repository prompt may be too
  large? That would change the Architect's design more than any classification does.
- Should a Loop ever prefer an organisation profile on purpose (for example a cross-board dependency
  check)? If yes, the rule needs an exception path with an explicit approval, not a silent fallback.

