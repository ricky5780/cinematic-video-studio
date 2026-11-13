# Changelog

## 1.1.0 — 2026-11-13

- Replace mandatory four-way implementation with four concepts → two real tests → one prototype.
- Add audit-only routing, early style lock, full-length rough cut and capability-aware fallback.
- Add explicit project-state initialization and dependency/output fingerprints for resumable work.
- Isolate every audit run; prevent stale screenshots/contact sheets from passing as fresh evidence.
- Scan complete media by default and label limited scans as partial.
- Index decoded video frames instead of using container duration minus a fixed offset.
- Split execution success from machine conformance; document exit codes 0/1/2.
- Add delivery-spec checks, EOF event handling, justified event allowances and audio measurements.
- Add bounded subprocesses, diagnostics, input-change invalidation and regression fixtures.
- Add guarded installation with backups outside skill discovery paths, MIT license and bilingual README.

Local tests do not certify real Codex/Lemo workflow behavior or film quality. See docs/VALIDATION.md.
