# AI Annotation Exchange Format & Local Import Contract v1

## 1. Overview
This contract defines the standard exchange format for external AI annotation runs (Gemini, GPT, Local CV) and how the desktop application imports, reviews, and audits AI-generated historical data without corrupting production ground truth.

## 2. State Machine Rules
```text
[Single Model AI Run] ──────> pseudo
                                 │
[Gemini + GPT Agreement] ───> strong_pseudo
                                 │
[Model Conflict / Red Item] ─> review_required
                                 │
[Human Accept / Verified SOT] > verified  (Only this state may write to production truth)
                                 │
[Human Reject] ─────────────> rejected
```

## 3. Local Importer Flow & Review Store Architecture
1. **Schema Validation**: Validate incoming annotation file against `annotation.schema.json`.
2. **Link Record & Screenshot**: Matches `recordId` and `screenshotRef` against historical database.
3. **Store in Isolated Review Store**: Written to local staging store (`.system_generated/review_store/`).
   - **STRICT PROHIBITION**: The importer **NEVER** overwrites `异环拍卖数据.json` directly.
4. **Promotion Protocol**: When human operator clicks `Accept` in History Review UI:
   - Slot status transitions: `pseudo / strong_pseudo -> verified`
   - Audit trail records: `priorValue`, `verifiedValue`, `verifiedBy`, `verifiedAt`, `sourceRunId`.
