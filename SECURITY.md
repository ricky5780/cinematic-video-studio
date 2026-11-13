# Security and privacy

- The audit accepts local files and runs subprocesses without a shell. It restricts FFmpeg input protocols to file/pipe.
- Run current FFmpeg in a sandbox for untrusted media. This project is not a media-decoder sandbox or vulnerability scanner.
- No API keys, service credentials, telemetry or paid services are required by the bundled Python tools.
- Logs contain execution arguments and may contain private local paths. Review evidence before publishing it.
- Installation never silently overwrites an existing skill; explicit replacement creates a backup outside the skill search path.
- Project dependency registration rejects files outside the project, including external symlink targets.
- Do not publish private footage, client assets, authentication information or unrelated repositories in bug reports.
- Report issues without secrets. If a token has already been exposed, revoke it with its issuer; do not paste it here.

No claim of a security audit or support SLA is made.
