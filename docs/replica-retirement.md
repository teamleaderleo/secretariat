# Reviewed replica retirement

Once a logical password has a readable authoritative home, Secretariat can verify that a recorded Chrome, Edge, or Apple replica still carries the same password and then forget that replica from the Garden in a separate explicit step.

The workflow does **not** delete anything from Chrome, Edge, Apple Passwords, or another external store. It only removes the copy metadata from the private Garden after convergence has been checked.

## Verify one replica

Use a fresh deliberate export from the target replica's source:

```text
secretariat \
  --garden /private/path/garden.json \
  replica verify example-login \
  --copy-id apple \
  --snapshot apple_passwords=/private/path/apple.csv \
  --receipt /private/path/example-login-apple-receipt.json
```

Secretariat requires:

- a password credential;
- the chosen copy to be a non-home replica;
- the target copy type to be Chrome, Edge, or Apple Passwords;
- the snapshot source to match that target copy;
- an explicit Garden `links.login` URL;
- an exact snapshot match on normalized login origin + Garden username;
- no conflicting password rows inside that source; and
- a readable current home.

For a KDBX home, verification uses the running unlock agent when available. Otherwise the existing KDBX backend can prompt for the master password. Secret Service homes use the existing native backend.

The current home password and target snapshot password are compared only in process memory with `hmac.compare_digest`. A mismatch produces no receipt.

## Convergence receipt

A successful check writes a new mode-0600 JSON receipt. It contains only:

- Garden alias;
- verification timestamp;
- Garden username and login URL;
- exact home copy id/type/reference;
- exact target replica id/type/reference;
- number of matching snapshot rows; and
- booleans saying whether those source rows contain notes or OTP metadata.

It contains no password value, password-derived hash/equality fingerprint, note contents, or OTP secret.

The receipt is review evidence, not a cryptographic authorization token. A user who can edit the private Garden already has the lower-level `garden detach` operation. The receipt workflow exists to make the safe, evidence-backed path easy and auditable.

## Retire the Garden replica

After reviewing the receipt:

```text
secretariat \
  --garden /private/path/garden.json \
  replica retire \
  --receipt /private/path/example-login-apple-receipt.json
```

Immediately before the atomic Garden edit, Secretariat re-checks that:

- the current home id/type/reference still matches the receipt;
- the target replica id/type/reference still matches;
- username and login URL still match; and
- the target replica has not become the home.

If any of those changed, the receipt is stale and retirement stops.

If the snapshot source carried notes or OTP metadata, retirement also stops until the user adds:

```text
--ack-attached-data
```

That acknowledgement means only that the user reviewed the attached-data warning. Secretariat still does not delete or move those external notes/OTP values.

A successful retirement uses the Garden's existing mode-0600 temporary write, fingerprint divergence check, schema validation, and atomic replacement. The authoritative home remains untouched.

## Source-side cleanup

After Garden retirement, the external password-manager record still exists. Secretariat reports the source type and explicitly says it was **not deleted**.

Delete or preserve that external record separately using the source's own supported UI/workflow. If notes or OTP metadata were present, handle those before deleting the source record.

This separation is intentional: proof that two password values matched does not grant Secretariat permission to delete data from another password manager.
