# NTE Architecture V2: Host-Engine IPC Compatibility & Evolution Policy

## 1. Versioning Scheme
The Host-Engine IPC protocol follows **Semantic Versioning 2.0.0** (`MAJOR.MINOR.PATCH`):
- **MAJOR** (`1.x.x` -> `2.0.0`): Breaking contract changes that require coordinated updates on both Host and Engine:
  - Modification of the 64-byte frame header binary struct layout or byte offsets.
  - Removal or type modification of required envelope fields.
  - Semantic changes to existing message types or core enum statuses.
- **MINOR** (`1.0.0` -> `1.1.0`): Backward-compatible enhancements:
  - Addition of new message types.
  - Addition of optional fields to existing message payloads.
  - Addition of new capability flags.
- **PATCH** (`1.0.0` -> `1.0.1`): Backward-compatible fixes, schema clarifications, and non-structural documentation changes.

---

## 2. Breaking Change Moratorium
During the active Strangler Migration lifecycle (phases `V2-0` through `V2-3`), **a strict breaking change moratorium is enforced**:
- `protocol_v1.json` envelope format is frozen.
- `frame_buffer_layout_v1.json` 64-byte binary header layout is strictly frozen.
- The 14 canonical message types defined in `message_catalog_v1.json` are frozen in names and core payload structures.
- Any proposed change requiring a `MAJOR` version bump requires an explicit RFC and re-audit before implementation.

---

## 3. Extensibility & Forward Compatibility Rules
To ensure resilience across differing build versions between the Host and Python Engine:
1. **Payload Openness**: Message payloads are open for additional optional fields. Implementations must tolerate unrecognized fields without throwing errors.
2. **Envelope Rigidity**: The 8 root envelope fields are closed and mandatory. Any message missing a root envelope field is rejected with `ERR_MALFORMED_ENVELOPE`.
3. **Fail-Closed Unknown Messages**: If a node receives an unrecognized `messageType`:
   - It must log an error with error code `ERR_UNKNOWN_MESSAGE_TYPE`.
   - It must discard the message fail-closed.
   - It must **not** terminate or crash the session if the message was non-critical.
4. **Binary Frame Header Invariance**: The 64-byte frame header has a reserved 4-byte padding field at offset 60 (`reserved`). Unused bits or flags must be set to 0.

---

## 4. Deprecation & Retirement Workflow
1. **Notice Phase**: A message type or payload field is marked `DEPRECATED` in `message_catalog_v1.json`.
2. **Transition Window**: The deprecated construct must remain accepted for at least one minor release cycle.
3. **Removal**: Deprecated constructs may only be removed upon a coordinated `MAJOR` version increment.
