# AI Evaluation

The model's judgement is not assumed to be correct. This file describes how it
gets checked.

Status: the framework is **specified**, and the deterministic half is
**implemented and tested**. The model-graded half needs API keys to run.

## What is already tested deterministically

Everything in `interview.py` — vagueness detection, thin-answer detection, depth
capping, topic advancement, wrap-up timing — is pure functions over state, tested
in `tests/test_interview_state.py`. These are the judgements the product makes
*without* a model, and they are the reason a model failure degrades the
interview rather than corrupting the assessment.

## Prompt versioning

Every prompt carries a version (`interviewer_v1`, in `prompts.py`) and that
version is recorded in the usage record for every generation it produced. An
assessment can always be traced to the exact prompt that produced it, and two
versions can be compared on the same inputs. Scoring methodology must never
change silently.

## The evaluation set (to build)

A fixed set of recorded candidate answers, each labelled by hand, covering:

| Category | What the system must do |
|---|---|
| Strong, correct answer | Not probe for weakness that isn't there; advance |
| Partially correct | Probe the missing part specifically |
| Confidently wrong | Challenge without revealing the right answer |
| Evasive / non-answer | Re-ask, do not accept and move on |
| Vague "we" behavioural answer | Demand individual contribution |
| Hallucinated resume claim | Cross-examine until the gap shows |
| Self-contradicting across turns | Notice and surface the contradiction |
| Technically plausible but wrong | Not be fooled by fluent phrasing |

## What gets measured

**Interviewer behaviour** (does it act like an interviewer?)
- Does it ever coach, hint, or reveal an answer? Any occurrence is a failure —
  this is Principle 5 and it is binary, not a gradient.
- Does it ever state or imply a score mid-interview?
- Filler-phrase rate ("That's interesting", "Great answer") per turn.
- Follow-up relevance: does the question engage the specific claim made?

**Assessment quality** (is the judgement right?)
- Agreement with human labels on the categories above.
- Calibration: when the system says "high confidence", is it more often right?
- Stability: same transcript, same prompt version, repeated runs — how much does
  the score move? A score that swings between runs is not a score.

**Cost and latency** per stage, measured, not estimated.

## Method

- Model-graded rubrics for the qualitative dimensions, with the grader prompt
  itself versioned and its agreement with human labels measured before it is
  trusted.
- Regression gate: a prompt change that reduces agreement on the eval set does
  not ship.
- Deliberately adversarial cases (injection attempts in the resume, a candidate
  who asks the interviewer to reveal the rubric) are part of the set, not a
  separate exercise.

## Honesty constraints on the output

These are product requirements, and they are testable:

- No numeric precision that the evidence does not support. `Python: Strong,
  confidence high, evidence: 3 correct answers` — not `Python: 83.291%`.
- "Not assessed" is never rendered as "weak".
- Model-derived judgements are labelled as such, separately from objective
  measurements (response duration, words per minute, filler count).
- No claims about the candidate as a person. Observable behaviour in this
  interview only.
