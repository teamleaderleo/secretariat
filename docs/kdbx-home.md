# Portable KDBX home

Secretariat can use a KDBX entry as the authoritative value for an enrolled credential. The Garden stores only the entry UUID. Each device separately configures where the encrypted database file is available.

## Install the optional adapter

```text
python -m pip install -e '.[kdbx]'
```

The `kdbx` extra currently uses PyKeePass 4.2 or newer for KDBX3/KDBX4 read and write access. PyKeePass is GPL-3.0 licensed; account for that dependency when choosing Secretariat's eventual public license and distribution model.

## Device configuration

macOS default config path:

```text
~/Library/Application Support/Secretariat/config.json
```

Linux default config path:

```text
${XDG_CONFIG_HOME:-~/.config}/secretariat/config.json
```

Example:

```json
{
  "kdbx": {
    "path": "/path/to/Google Drive/Secretariat/secretariat.kdbx"
  }
}
```

`SECRETARIAT_CONFIG` can point at a different config file. `SECRETARIAT_KDBX_PATH` can override the KDBX path for a process. The database master password is deliberately absent from both configuration mechanisms; interactive CLI operations prompt for it when the KDBX home is opened.

## Garden copy

A KDBX copy uses the entry UUID as exactly 32 lowercase hexadecimal characters:

```json
{
  "id": "portable",
  "type": "kdbx",
  "reference": "00112233445566778899aabbccddeeff"
}
```

Titles and group paths are mutable and may be ambiguous, so Secretariat rejects them as KDBX identity. The current KeePassXC command-line client still lacks an exact UUID selection command; the adapter therefore uses PyKeePass's UUID lookup rather than title/path matching.

## Reads

`copy` and `run` can read a KDBX home once the optional dependency and device path are available. Secretariat resolves exactly one entry by UUID and reads its protected Password field.

Passkeys are excluded from this generic value path. They remain in platform credential-provider/exchange APIs.

## Writes and conflicts

Before changing an entry, Secretariat records a fingerprint of the encrypted KDBX file, saves the previous entry version into KDBX history, updates the password field, and writes a new encrypted database to a mode-0600 temporary file in the same directory.

Immediately before replacing the home file, Secretariat verifies that the original encrypted file is unchanged. If another process or cloud transport changed it, the write stops with a divergence error. The temporary file is discarded and the competing revision stays intact for review.

A successful write uses an atomic same-directory replacement where the platform supports it. Cloud version history remains valuable recovery evidence.

## Transport boundary

Secretariat has no Google Drive credentials or cloud API code in the KDBX adapter. A transport such as Google Drive, rclone, Syncthing, Dropbox, or Nextcloud only moves the already-encrypted KDBX file between devices.

For a Mac/Linux setup using Google Drive:

```text
Mac provider/browser -> Secretariat -> KDBX -> Google Drive -> Linux -> Secretariat
```

Google Drive for desktop can supply the Mac path. Linux can use a separately configured Drive client such as rclone. Those transport credentials and paths stay in device configuration outside the Garden.

## Current scope

This first adapter updates existing UUID-backed entries. Creating/enrolling new KDBX entries, key-file/hardware-key unlock, automated native-keyring unlock, and cross-revision merge UI are separate follow-up work. Generated databases should be used while exercising those flows.
