# Reconciliation

Secretariat's first unification step is read-only comparison.

Temporary exports from Chrome, Edge, and Apple Passwords are loaded in memory and grouped by a conservative normalized website origin plus username. Groups are classified as:

- `single` — one observed copy;
- `duplicate` — several copies with the same password value;
- `conflict` — several copies with different password values.

Different usernames at the same site remain separate accounts. Duplicate rows inside a single source remain visible.

Password values are compared only in process memory. Reports expose no password value, hash, reusable equality fingerprint, note contents, or OTP secret. They may report which source carries notes or OTP metadata so cleanup does not discard unique attached data.

## Workflow

1. Export the stores deliberately to private temporary files.
2. Run `secretariat reconcile` against those snapshots.
3. Review conflicts first, then duplicates, then single copies.
4. Decide the logical credential and desired home.
5. Populate the private Garden only after the decision is clear.
6. Delete plaintext exports when the review is finished.

Reconciliation does not mutate password stores or the Garden.
