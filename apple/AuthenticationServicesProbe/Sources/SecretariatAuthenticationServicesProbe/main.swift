import AuthenticationServices
import Foundation

enum ProbeFailure: Error {
  case invariant(String)
}

@main
struct AuthenticationServicesProbe {
  static func main() async throws {
    try probePasswordIdentity()
    try probePasskeyIdentityMetadata()
    if #available(macOS 26.1, *) {
      try probeCredentialExchangeModel()
    } else {
      print("credential-exchange-v1-model: unavailable")
    }
    await probeIdentityStoreState()
  }

  private static func probePasswordIdentity() throws {
    let recordIdentifier = "generated-password-\(UUID().uuidString)"
    let service = ASCredentialServiceIdentifier(
      identifier: "login.secretariat.invalid",
      type: .domain
    )
    let identity = ASPasswordCredentialIdentity(
      serviceIdentifier: service,
      user: "generated-user",
      recordIdentifier: recordIdentifier
    )
    let request = ASPasswordCredentialRequest(credentialIdentity: identity)

    guard request.credentialIdentity.recordIdentifier == recordIdentifier else {
      throw ProbeFailure.invariant("password request changed the provider record identifier")
    }
    print("password-identity: pass")
  }

  private static func probePasskeyIdentityMetadata() throws {
    let recordIdentifier = "generated-passkey-\(UUID().uuidString)"
    let identity = ASPasskeyCredentialIdentity(
      relyingPartyIdentifier: "passkey.secretariat.invalid",
      userName: "generated-user",
      credentialID: Data(UUID().uuidString.utf8),
      userHandle: Data(UUID().uuidString.utf8),
      recordIdentifier: recordIdentifier
    )

    guard identity.recordIdentifier == recordIdentifier else {
      throw ProbeFailure.invariant("passkey identity changed the provider record identifier")
    }
    print("passkey-identity-metadata: pass")
  }

  @available(macOS 26.1, *)
  private static func probeCredentialExchangeModel() throws {
    let password = "generated-only-\(UUID().uuidString)"
    let credential = ASImportableCredential.basicAuthentication(
      .init(
        userName: .init(
          id: nil,
          fieldType: .string,
          value: "generated-user"
        ),
        password: .init(
          id: nil,
          fieldType: .concealedString,
          value: password
        )
      )
    )
    let item = ASImportableItem(
      id: Data(UUID().uuidString.utf8),
      title: "Generated Secretariat login",
      scope: .init(urls: [URL(string: "https://login.secretariat.invalid")!]),
      credentials: [credential]
    )
    let account = ASImportableAccount(
      id: Data(UUID().uuidString.utf8),
      userName: "generated-user",
      email: "generated-user@secretariat.invalid",
      collections: [],
      items: [item]
    )
    let exported = ASExportedCredentialData(
      accounts: [account],
      formatVersion: .v1,
      exporterRelyingPartyIdentifier: "secretariat.invalid",
      exporterDisplayName: "Secretariat generated-data probe",
      timestamp: Date()
    )

    guard exported.accounts.count == 1, exported.formatVersion == .v1 else {
      throw ProbeFailure.invariant("credential exchange model changed generated account data")
    }
    print("credential-exchange-v1-model: pass")
  }

  private static func probeIdentityStoreState() async {
    await withCheckedContinuation { continuation in
      ASCredentialIdentityStore.shared.getState { state in
        print(
          "identity-store-state: enabled=\(state.isEnabled) "
            + "incremental=\(state.supportsIncrementalUpdates)"
        )
        continuation.resume()
      }
    }
  }
}
