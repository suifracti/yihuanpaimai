# Saved-frame amount regression

Links the production `SceneAnchorOcr.cs`; no capture, window discovery or input.

From the repository root on Windows with the Chinese Windows OCR language:

```powershell
dotnet run --project tests/native_scene_ocr/scene-ocr.csproj -c Release
```

The two anonymous numeric crops are real saved lobby/auction pixels, with
source hashes and rectangles alongside each fixture. They are not fresh
balances, qualified SOURCEs or evidence of general OCR accuracy.
The old production reader returns null for the lobby fixture because Windows
OCR inserts whitespace around thousands separators. The full old lobby ROI
also truncates the first digits; including the currency icon yields a false
extra zero. Production therefore selects a numeric ROI by recognized scene.

`--parser-only` checks the amount parser and scene region selection without
calling the Windows OCR engine. CI uses this mode; it does not claim to run
the two real OCR fixtures. Local before/after OCR logs and raw OCR text are
preserved under `build/goal-20261020-ocr/`.
