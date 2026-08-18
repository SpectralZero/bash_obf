# Security Policy

## Supported Version

Security fixes are evaluated for the current reviewed internal development line. No public support window, hosted service, or public release channel is offered. Internal release owners decide whether an older approved artifact requires a backport or withdrawal.

## Reporting

Report suspected vulnerabilities through the organization's approved private security or incident-response channel and identify the report as concerning `obfush`. Do not include exploit details, proprietary source, generated payloads, customer data, credentials, or environment keys in a public issue, discussion, chat room, or third-party paste service.

No repository-specific public security address or external disclosure portal is asserted here because none is configured in the repository. Assignment of a durable reporting contact and response SLA is externally pending. Until then, authorized users must use their existing internal security escalation path and preserve evidence according to organizational policy.

Include the affected commit or internal artifact checksum, platform and Python version, minimal benign reproduction, impact assessment, and whether input execution or binary compilation is involved. Coordinate disclosure and remediation privately with the authorized owner.

## Operational Security

- Run `--verify` only on trusted, authorized scripts in an operator-provided isolated environment; verification executes input and generated code.
- Treat generated scripts and binaries as sensitive executable artifacts with the same authorization scope as their source.
- Do not place secrets in source merely because it will be obfuscated. Obfuscation is not encryption and runtime inspection can recover content and behavior.
- Protect configuration, seeds, logs, JSON metadata, environment-binding values, checksums, and workflow artifacts according to engagement requirements.
- Review dependency and compiler provenance. A compromised build dependency or compiler can alter generated artifacts.
- Use checksums for transfer integrity, but do not treat an untrusted checksum as provenance or a substitute for organizational signing.

The detailed security assumptions and non-goals are in `docs/threat-model.md`. The license restricts use and redistribution and remains authoritative.
