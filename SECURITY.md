# Security policy

The current 0.1.x line receives security fixes. This is a personal, single-user application intended for a trusted LAN or VPN; no multi-user security certification is claimed.

Report vulnerabilities privately through [GitHub security advisories](https://github.com/lucas-lepajollec/sillage/security/advisories/new) or the maintainer's established security contact, security@lucaslepajollec.com. Do not attach real credentials, private media or database backups to public issues.

## Boundaries

- Media roots confine navigation and processing; MKVs are read-only to application logic. Sidecar publication is atomic and exclusive.
- Provider keys are encrypted with a separate key under /config. Administrators who can read both can decrypt them. Keep the entire config directory and backups private.
- Translation sends subtitle text/context/glossary to the selected provider. HTTP LAN endpoints are supported; choose HTTPS or a trusted network when confidentiality matters.
- Compose publishes port 5775 on host interfaces, as a normal self-hosted service. Use trusted networks and a firewall. For broader exposure, configure ACCESS_KEY, HTTPS and a reverse proxy. See [Docker operations](docs/docker.md).
- Authentication is an optional shared access key, not a multi-user identity system. No rate-limiting, adversarial filesystem sandbox or independent audit is claimed.

Never enable provider HTTP body/header debug logging with real data. Preserve the secret key with the database when restoring. See [limitations](docs/limits.md) for the distinction between timing preservation, heuristic audio alignment and real-player validation.
