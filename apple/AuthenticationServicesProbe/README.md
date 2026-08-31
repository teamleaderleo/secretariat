# AuthenticationServices capability probe

This is a generated-data-only macOS probe for the public AuthenticationServices types Secretariat would use. It proves that the current SDK can construct:

- password identities and typed password requests with a stable provider record identifier;
- passkey identity metadata with a stable provider record identifier;
- a version 1 credential-exchange model containing one generated password on macOS 26.1 or newer; and
- the value-free credential identity store state.

The probe never prints, encodes, writes, imports, or exports the generated password. It does not create passkey key material. Its output contains capability verdicts and the two identity-store state booleans only.

Run it on macOS 26 with Xcode 26:

```sh
cd apple/AuthenticationServicesProbe
swift run
```

This command-line target deliberately stops short of an installable AutoFill extension. A real extension and its containing app must both be signed with Apple's `com.apple.developer.authentication-services.autofill-credential-provider` entitlement and then enabled by the user in System Settings. Credential exchange additionally requires the extension capability keys `SupportsCredentialExchange = true` and `SupportedCredentialExchangeVersions = ["1.0"]`; initiating an exchange presents Apple's out-of-process consent UI.

Password save/update requests are not a macOS prototype path in the current SDK. Xcode 26.6 exposes `ASSavePasswordRequest`, but its provider callbacks and completion API are available on iOS and visionOS 26.2 and explicitly unavailable on macOS.

Apple references:

- [AutoFill Credential Provider entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.authentication-services.autofill-credential-provider)
- [ASCredentialExportManager](https://developer.apple.com/documentation/authenticationservices/ascredentialexportmanager)
- [ASCredentialImportManager](https://developer.apple.com/documentation/authenticationservices/ascredentialimportmanager)
