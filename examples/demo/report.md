# A/B test report: demo_conversion

- **Status:** `completed`
- **Generated (UTC):** 2026-11-17T04:50:54.587227+00:00
- **Pipeline version:** `0.1.0`
- **Input SHA-256:** `6eb267fb1d7550b521a2434921b222106f73ef46749f479a2fd71d77d8f2f9ca`
- **Config SHA-256:** `15996ca97307f9a9800420e630e40eef90b2e99f49df8c3bcf75fe7a0b5c3279`
- **Git commit:** `506f42c1e720204a2744c6b20f55f40283b7b8f3`
- **Git worktree dirty:** `True`
- **Seed:** `41`

## Data checks

- Rows: 2400
- Validation: passed
- SRM: passed (p=1, alpha=0.001)
- Observed assignments: `{"control": 1200, "treatment": 1200}`

## Metrics

| Metric | Role | Control | Treatment | Difference | 95% CI | p-value | Test |
|---|---|---:|---:|---:|---:|---:|---|
| conversion | primary | 0.1175 | 0.148333 | 0.0308333 | [0.00369743, 0.0579692] | 0.0260998 | two_proportion_z_test |
| revenue | guardrail | 2.13452 | 2.57584 | 0.441328 | [-0.177351, 1.06001] | 0.161994 | welch_t_test |

## Subgroups

| Dimension | Value | Metric | Difference | p-value | Adjusted p-value |
|---|---|---|---:|---:|---:|
| country | CA | conversion | -0.0365382 | 0.310438 | 0.310438 |
| country | CA | revenue | -0.228127 | 0.751179 | 0.934332 |
| country | GB | conversion | 0.0527016 | 0.0521795 | 0.104359 |
| country | GB | revenue | 0.538427 | 0.467166 | 0.934332 |
| country | US | conversion | 0.0391033 | 0.0298824 | 0.0896471 |
| country | US | revenue | 0.570608 | 0.141455 | 0.424366 |

## MDE and power

- Approximate detectable absolute effect: 0.03754
- Configured planned MDE: 0.03
- Approximate power at planned MDE: 0.620
- These normal-approximation values are planning diagnostics, not evidence that a non-significant result means no effect.

## Interpretation note

This report is an analytical artifact, not a business recommendation. Review the experiment design, SRM status, guardrails, and practical effect size before making a decision.
