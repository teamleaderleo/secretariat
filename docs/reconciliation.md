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

## Cleanup boundary

Applying a plan records the observed Chrome/Edge/Apple copies and the chosen home relationship. It does not delete or overwrite anything in those external password stores. Source-side cleanup and replica retirement remain separate reviewed operations.

Delete plaintext CSV exports when the review is finished. The HTML report and reviewed plan contain no credential values, but they do contain private sites/usernames/source metadata, so keep or remove them according to your own retention needs.
