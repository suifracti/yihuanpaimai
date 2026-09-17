# NTE Architecture V2: Host-Engine IPC Compatibility & Evolution Policy

## 1. Versioning Scheme
The Host-Engine IPC protocol follows **Semantic Versioning 2.0.0** (`MAJOR.MINOR.PATCH`):
- **MAJOR** (`1.x.x` -> `2.0.0`): Breaking contract changes that require coordinated updates on both Host and Engine.
- **MINOR** (`1.0.0` -> `1.1.0`): Backward-compatible additions (optional payload fields, new message types).
- **PATCH** (`1.0.0` -> `1.0.1`): Backward-compatible clarifications and non-structural documentation changes.

---

## 2. Strangler Migration Exact Match Moratorium (V2-0 through V2-3)
During the active Strangler Migration lifecycle (phases `V2-0` through `V2-3`), **an exact version equality policy (`protocolVersion == '1.0.0'`) is strictly enforced**:
- All implementations (Host and Engine) must advertise and validate `protocolVersion: "1.0.0"`.
- Any version string other than `"1.0.0"` is rejected fail-closed with `ERR_PROTOCOL_VERSION_MISMATCH`.
- The 64-byte frame header binary layout, 4-slot ring buffer geometry, and the 14 canonical message types are strictly frozen.
- Minor version backward-compatibility negotiation will only be unlocked post-strangler general availability via formal RFC.

---

## 3. Extensibility & Forward Compatibility Rules
1. **Payload Strictness**: Message payloads must adhere to declared schemas and types in `message_catalog_v1.json`. Coercion of numbers, booleans, or nulls into strings is strictly prohibited.
2. **Envelope Rigidity**: The 8 root envelope fields are closed and mandatory. Any missing field triggers `ERR_MALFORMED_ENVELOPE`.
3. **Fail-Closed Unknown Messages**: If a node receives an unrecognized `messageType`:
   - It logs `ERR_UNKNOWN_MESSAGE_TYPE`.
   - It discards the message fail-closed.
4. **Binary Frame Header Invariance**: The 64-byte frame header has a reserved 4-byte padding field at offset 60 (`reserved`). Unused bits or flags must be set to 0.

---

## 4. Deprecation & Retirement Workflow
1. **Notice Phase**: A message type or payload field is marked `DEPRECATED` in `message_catalog_v1.json`.
2. **Transition Window**: The deprecated construct must remain accepted for at least one minor release cycle.
3. **Removal**: Deprecated constructs may only be removed upon a coordinated `MAJOR` version increment.
