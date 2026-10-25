# Usage Report: Model Calls, Tokens & Execution Costs

This report documents the token usage, model providers, and costs for the solution that produced the submitted `output.csv`, in strict accordance with `AGENTS.md` §6.8.

To maintain complete transparency and auditability, this report explicitly distinguishes between the **initial cache preparation phase** (when external API calls occurred) and the **final evaluation run** (which replayed the precomputed cache).

---

## 1. Executive Summary

| Phase | Execution Date | Model Calls | Input Tokens | Output Tokens | Total Tokens | API Cost (USD) |
|---|---|---:|---:|---:|---:|---:|
| **Cache Preparation** (Live API Extraction) | 24 Oct 2026 | 48 | 68,995 | 7,257 | 76,252 | $0.4211 |
| **Final Submission Run** (`main.py --offline`) | 25 Oct 2026 | **0** | **0** | **0** | **0** | **$0.0000** |
| **Combined Lifecycle Total** | | **48** | **68,995** | **7,257** | **76,252** | **$0.4211** |

- **Average Tokens per Evaluation Request (518 cases):** 147 tokens/case
- **Estimated Cost per Evaluation Request (518 cases):** $0.00081/case
- **Token Count Measurement:** Directly measured from provider API headers (`response.usage`), logged line-by-line to `code/cache/usage_log.jsonl`.
- **Cost Calculation:** Estimated using Anthropic standard list pricing without volume or caching discounts ($4.00 / MTok in, $20.00 / MTok out).

---

## 2. Phase 1: Cache Preparation (Live Model Extraction)

The solution uses AI solely where evidence requires vision or linguistic understanding rather than deterministic parsing:

| Task / Purpose | Description & Inputs | Model | Measured Calls | Input Tokens (Measured) | Output Tokens (Measured) | Estimated Cost (USD) |
|---|---|---|---:|---:|---:|---:|
| `visual_extraction` | 11 PNG screenshots (base64) & 4 PDF text layers | Anthropic `claude-opus-5-5` | 15 | 50,938 | 4,885 | $0.3015 |
| `intent_classification` | Ambiguous request texts not matching standard opening phrases (33 of 550 total requests) | Anthropic `claude-opus-5-5` | 33 | 18,057 | 2,372 | $0.1197 |
| **Phase 1 Totals** | | | **48** | **68,995** | **7,257** | **$0.4211** |

All live calls used rigid JSON schema enforcement (`output_config.format` with `additionalProperties: False`) and `effort: "low"`.

---

## 3. Phase 2: Final Evaluation Run (`python3 code/main.py`)

The final run generating the submitted `output.csv` across all 518 evaluation requests ran in offline mode using the committed cache [`code/cache/llm_cache.json`](code/cache/llm_cache.json):

```bash
python3 code/main.py --offline
```

- **New Live Model Calls:** 0
- **New Input / Output Tokens:** 0 / 0
- **New Cost Incurred:** $0.00
- **Execution Time:** ~4.1 seconds across all 518 cases
- **Cache Mechanism:** Responses are indexed by the SHA-256 hash of `(model_name, prompt_version, canonical_input_bytes)`. A match returns the cached JSON directly, ensuring 100% deterministic bit-for-bit reproducibility across runs and environments without requiring network access or external API keys.

---

## 4. Per-Request Averages & Pricing Model

### Pricing Schedule
- `claude-opus-5-5`: $4.00 per million input tokens, $20.00 per million output tokens (Anthropic published standard list price).

### Breakdown Across Dataset
- **518 Evaluation Cases:**
  - Average tokens per request: $\frac{76,252}{518} \approx 147.2$ tokens
  - Average cost per request: $\frac{\$0.4211}{518} \approx \$0.000813$
- **All 550 Requests (including 32 public samples processed globally for batch linking):**
  - Average tokens per request: $\frac{76,252}{550} \approx 138.6$ tokens
  - Average cost per request: $\frac{\$0.4211}{550} \approx \$0.000766$

---

## 5. Audit & Reproduction

The raw per-call ledger is committed in [`code/cache/usage_log.jsonl`](code/cache/usage_log.jsonl). It can be audited or regenerated at any time using:

```bash
python3 code/evaluation/usage.py
```
