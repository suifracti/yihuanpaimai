# Vision Benchmark v1 (Model Agreement & Human Verification Framework)

## 1. Provenance & Current Status
- **Current Mode**: `Model Agreement Benchmark`
- **Independent Verified Ground Truth Count**: `0` (All initial detections are model-derived pseudo-labels).
- **Red Item Provenance**: Marked strictly as `gemini_pseudo_label` (Unverified).

## 2. Multi-Model Consensus Protocol (Gemini + GPT)
1. **Gemini Blind Predictions**: Frozen in `gemini_blind_predictions.json` (43 slots) and `pseudo_labels.json` (57 slots).
2. **GPT Pure Blind Queue**: Contained in `gpt_blind_queue.json` (19 priority slots). **Contains zero Gemini predictions or quality hints.**
3. **Consensus Semantics**:
   - `Gemini + GPT 独立一致` $\implies$ `Strong Multi-Model Pseudo-Label` (高置信度多模型伪标签).
   - **严禁直接作为正式真值写入历史生产数据**。
   - **只有人工操作者确认或存在独立物理真值时，才能晋升为 verified truth 并写入历史数据。**

## 3. Human 1-Click Verification Protocol
- Human reviewers use `human_review_queue.json`:
  - Input: Crop + Gemini Top-3 + GPT Top-3 + Catalog Reference Image.
  - Action: 1-click select confirmed `itemId` or `unknown` (2~5 seconds per slot).
  - Output: Promoted to `ground_truth.json` with `verifiedBy: "human"`, `truthSource: "human_confirmed"`.
