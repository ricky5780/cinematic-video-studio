# Cinematic Video Studio

A Chinese-first Codex skill for evidence-driven video preproduction, prototypes, production, focused revisions and review.
**Version 1.1.0 · MIT.** [中文文档](README.md)

It is an orchestration skill, not a video model or rendering engine. It can use an existing Lemo-Opuscar installation
or another available pipeline; it does not bundle or modify third-party engines or grant missing capabilities.

## Install

From a checked-out source directory:

```sh
python3 install.py
```

Default destination: `~/.agents/skills/cinematic-video-studio/`. On Windows use `py -3` if appropriate.
Existing installs are protected. `--replace` backs them up outside the skills search directory.
No network access, dependency installation, or global configuration changes occur during installation.

Invoke in Codex with `$cinematic-video-studio` and your actual brief.
Modes: explore, prototype, produce, refine, audit. Existing styles skip unnecessary exploration;
audit-only requests never authorize rewriting or re-rendering the project.

## Technical audit

Python 3.10+ and FFmpeg/FFprobe on PATH are required for media analysis.

```sh
python3 scripts/doctor.py
python3 scripts/video_audit.py film.mp4 --output qa --spec delivery-spec.json
python3 -m unittest discover -s tests -v
```

Adapt `templates/delivery-spec.json` to the project. Each audit creates an isolated run with input hashes,
command logs, fresh representative frames, a contact sheet and JSON/Markdown reports.
The default anomaly scan covers the complete selected video/audio streams. Full frame indexing locates the real final video frame,
including low-frame-rate clips and videos shorter than their soundtracks.

Exit codes: **0** configured machine checks passed; **1** warning, spec failure, missing spec or incomplete coverage;
**2** input/tool/execution failure. **None of these certify aesthetics, listening, factual accuracy, licensing, or semantic sync.**
Designed black/frozen/silent intervals need explicit, justified allowances. Manual review remains separate.

## Limits

Only the first non-cover video and first audio stream are analyzed; additional streams trigger a warning.
Full frame indexing uses memory and may be costly for long media. Anomaly filters are heuristics.
No automatic OCR, beauty score, speech correctness evaluation, licensing check or background execution is provided.
Local integration tests do not establish Codex/Lemo end-to-end compatibility; see [validation](docs/VALIDATION.md).

Dependency-hash-based resumption is explicit: register all source, assets, configuration, seeds and environment manifests.
Cache validity is not creative approval. See the Chinese production and quality reference documents for the full contract.

MIT covers only this project's code and documentation, not third-party media, fonts, music or data.
