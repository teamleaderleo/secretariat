# Architecture

Secretariat separates logical credential identity from the places that store or present a credential.

## Logical credential

A Garden entry represents one account or credential. It can have several `copies`, such as an Apple Passwords record, a browser record, a native keyring item, or a KDBX entry. When several copies exist, one copy is named as `home`.

The home is the authoritative value location for Secretariat operations. Other copies are interfaces, migration sources, or replicas.

## Three data locations

A typical setup separates:

1. **Secretariat code** — reusable public software;
2. **Garden metadata** — private Git data containing account/source relationships but no credential values;
3. **credential values** — encrypted KDBX or reviewed native stores outside Git.

Machine-specific paths and unlock/cloud credentials stay in machine configuration outside the Garden.

## Cross-device home

The planned portable home is an encrypted KDBX database whose file is transported independently of Git. Each device maps the same Garden KDBX UUID to its own machine-specific database path and unlock method.

Native password managers do not need to talk directly to one another. They can interact with the same logical home through Secretariat provider integrations.

## Conflict rule

Secretariat never chooses a winning divergent credential merely because one timestamp is newer. Competing revisions become a review state. Deletion and replica retirement are explicit so stale copies cannot silently resurrect an old credential.
