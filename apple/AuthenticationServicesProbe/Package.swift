// swift-tools-version: 6.2

import PackageDescription

let package = Package(
  name: "SecretariatAuthenticationServicesProbe",
  platforms: [.macOS(.v26)],
  products: [
    .executable(
      name: "secretariat-authentication-services-probe",
      targets: ["SecretariatAuthenticationServicesProbe"]
    )
  ],
  targets: [
    .executableTarget(name: "SecretariatAuthenticationServicesProbe")
  ]
)
