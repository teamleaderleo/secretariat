# Security policy

Secretariat coordinates credential metadata and, through reviewed adapters, may cross real secret boundaries.

Report as security defects:

- a credential value entering stdout, stderr, logs, Garden JSON, Git, process argv, ordinary temporary files, or persistent clipboard history;
- Garden parsing that accepts unknown or value-bearing fields;
- a source adapter falling back to plaintext storage;
- copy/reference confusion that retrieves or updates a different credential than requested;
- an indexed-only copy unexpectedly gaining value access;
- reconciliation output containing passwords, password-derived fingerprints, note contents, or OTP secrets;
- propagation choosing a target or winning revision silently when copies diverge;
- provider mutation, rotation, revocation, import, or deletion without an exact identity and confirmation boundary.

## Public repository boundary

This repository must contain only reusable software, generated fixtures, and public documentation. Real Gardens, browser/password-manager exports, reconciliation reports, KDBX databases, device configuration, cloud credentials, and private account inventories belong elsewhere.

## Snapshot handling

CSV exports from password managers are plaintext secret material. Secretariat's reconciliation command reads user-selected snapshots, compares values only in process memory, and emits secret-free metadata. Snapshot files should be deleted when the review is complete.

## Indexed copies

A copy may be represented before Secretariat can read or write its value. Indexed-only copy types must refuse value operations until a reviewed adapter proves exact identity and bounded secret handling.

Metadata disclosure still deserves care: Gardens and reconciliation reports can reveal private sites, usernames, provider identifiers, and device relationships even when they contain no credential values.
