# History Admission Policy v1

`history-admission.v1` is the single read-only authority for deciding whether a persisted row may enter History views and match counts. The executable authority is `app/history_admission.py`; consumers must not copy its rules.

## Separate states

- `record exists`: the JSON row is present.
- `history admitted`: lifecycle/identity/time/legacy compatibility passed.
- `high-confidence ground truth`: a field-specific Truth Evidence contract passed.
- `evaluation eligible`: History, duplicate, truth, prediction, temporal, target/mode, and model-cohort gates all passed.

Admission never implies that every field is reliable.

## Policy

1. Exclude invalid records, missing IDs, all members of duplicate-ID groups, DRAFT, CANCELLED/CANCELED, diagnostic, unsupported lifecycle, and invalid timestamps.
2. Admit explicit FINALIZED records after structural checks.
3. Legacy rows without lifecycle are admitted only by the existing compatibility gates:
   - nested settlement has `status=verified`, `verified=true`, and positive actual total; or
   - source is `0.65-vision-auto-archiver` with positive actual and clearing values.
4. A naive legacy timestamp is interpreted as `Asia/Shanghai` and flagged `LEGACY_TIMESTAMP_ASSUMED_ASIA_SHANGHAI`.
5. Potential content duplicates are flagged for History, never deleted, and fail closed for Evaluation.

## Version and reason ownership

- Policy version: `1`.
- Exclusion and flag constants live only in `app/history_admission.py`.
- `MainViewStateProvider`, History, and Evaluation must call that module.

## Duplicate contracts

- Exact ID duplicate: every member excluded.
- Potential content duplicate fingerprint v1: normalized played time + actual total + clearing price + venue + box. It is a review signal, not automatic deletion authority.

## Timestamp contract

- `playedAt`, then declared legacy `timestamp` fallback.
- Explicit offsets are converted to `Asia/Shanghai` for local windows.
- Naive legacy values are assigned `Asia/Shanghai`, never machine-local timezone.
- New Prediction/Truth contract timestamps must be offset-aware; the legacy assumption applies only to persisted match time.
