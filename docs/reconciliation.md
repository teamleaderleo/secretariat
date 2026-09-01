# Reconciliation and Garden enrollment

Secretariat compares deliberate temporary exports from Chrome, Edge, and Apple Passwords without writing back to those stores.

Snapshots are loaded in memory and grouped by a conservative normalized website origin plus username. Groups are classified as:

- `single` — one observed copy;
- `duplicate` — several copies with the same password value;
- `conflict` — several copies with different password values.

Different usernames at the same site remain separate accounts. Duplicate rows inside a single source remain visible. When rows inside the same source disagree on the password, the report marks that source as ambiguous and blocks Garden enrollment until the source itself is cleaned up; a CSV row number is not a durable credential identity.

Password values are compared only in process memory. Reports and reviewed plans expose no password value, password-derived hash/fingerprint, note contents, or OTP secret. They may report which source carries notes or OTP metadata so cleanup does not discard unique attached data.

## Review workflow

Create private temporary exports, then render the self-contained review:

```text
secretariat reconcile \
  --snapshot chrome_passwords=/private/path/chrome.csv \
  --snapshot edge_passwords=/private/path/edge.csv \
  --snapshot apple_passwords=/private/path/apple.csv \
  --html /private/path/secretariat-review.html
```

In the HTML report:

1. Filter conflicts, duplicates, and single copies as needed.
2. Select only the logical credentials you want to enroll.
3. Edit each proposed Garden alias.
4. For multi-source entries, explicitly choose one source copy as home.
5. Download `secretariat-garden-plan.json`.

Nothing in the HTML modifies the Garden or any password store. The downloaded file is private account metadata and should stay outside the public repository.

## Reviewed plan format

The downloaded plan is a strict, versioned format intentionally narrower than the Garden:

```json
{
  "schema_version": 1,
  "entries": [
    {
      "alias": "example.com-generated-user-example.invalid",
      "title": "Example",
      "username": "generated-user@example.invalid",
      "provider": "example.com",
      "login": "https://example.com",
      "copies": [
        {
          "id": "chrome",
          "type": "chrome_passwords",
          "reference": "https://example.com account=generated-user@example.invalid"
        },
        {
          "id": "apple",
          "type": "apple_passwords",
          "reference": "https://example.com account=generated-user@example.invalid"
        }
      ],
      "home": "apple"
    }
  ]
}
```

Only Chrome, Edge, and Apple snapshot copies are accepted in this plan format. Every source is collapsed to one logical copy. A multi-copy entry must name one of those copies as `home`.

The references are metadata identities, not secret fingerprints. For unusually long metadata Secretariat may use a SHA-256 digest of the origin/username metadata so the Garden reference remains bounded; it never hashes a password value for identity or equality.

## Apply the reviewed plan

Apply it to the private Garden explicitly:

```text
secretariat \
  --garden /private/path/secretariat-garden/garden.json \
  garden apply-plan \
  --plan /private/path/secretariat-garden-plan.json
```

The first implementation only **adds new logical credentials**. It does not merge into or overwrite existing aliases. The whole plan is validated before the Garden is changed. Alias collisions, unknown fields, unsupported sources, missing homes, invalid Garden metadata, or a competing Garden revision stop the operation.

Successful application uses the same mode-0600 same-directory temporary write and atomic replacement as other Garden edits. A failure anywhere leaves the Garden unchanged.

## Promote a reviewed snapshot home into KDBX

After plan application, a credential may deliberately still have `chrome_passwords`, `edge_passwords`, or `apple_passwords` as its home. Those copies are useful reconciliation identities but do not provide Secretariat value access.

To move one reviewed account into the portable encrypted KDBX home, keep the deliberate temporary export for that chosen source long enough to run:

```text
secretariat \
  --garden /private/path/secretariat-garden/garden.json \
  migrate to-kdbx example.com-generated-user-example.invalid \
  --snapshot apple_passwords=/private/path/apple.csv
```

The command requires the supplied snapshot source to match the Garden credential's **current home**. It identifies the snapshot row only by the Garden `links.login` origin plus Garden username. Titles are never used to guess identity.

If several rows in that source match the same account, they are accepted only when their passwords compare equal in memory. Conflicting rows stop the migration.

The migration then:

1. preflights attaching a canonical `portable` KDBX copy and making it home without changing the Garden yet;
2. prompts for the configured KDBX master password through the existing KDBX adapter;
3. writes the selected snapshot password into a new encrypted KDBX entry and receives its exact UUID;
4. substitutes that UUID into the preflighted Garden edit; and
5. commits the Garden only if its original file fingerprint still matches.

The password is never put in the reviewed plan, Garden, stdout, logs, or a metadata hash.

KDBX and Garden are two independent durable stores, so no implementation can make that final two-file operation perfectly atomic. If another editor/Git process changes the Garden after the KDBX entry is created but before the Garden commit, Secretariat **does not delete the new encrypted entry automatically**. It reports the UUID and a metadata-only `garden attach ... --home` recovery command. That leaves a harmless orphaned encrypted KDBX entry rather than risking deletion from the wrong database revision.

The original Chrome/Edge/Apple copy remains recorded as a replica. Promotion does not delete or overwrite any external password-manager record.

## Cleanup boundary

Applying a plan records the observed Chrome/Edge/Apple copies and the chosen home relationship. Promoting an entry into KDBX creates the portable home but still does not delete external replicas. Source-side cleanup and replica retirement remain separate reviewed operations.

Delete plaintext CSV exports after the review/migration work that needs them is finished. The HTML report and reviewed plan contain no credential values, but they do contain private sites/usernames/source metadata, so keep or remove them according to your own retention needs.
