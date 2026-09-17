# Approved Locations verification

Date: 2026-09-17. Runtime: Windows, Python 3.12.10.

## Baseline and scope

Before editing, `git status --short`, `git log -1 --oneline`, AGENTS.md and the shared filesystem root implementation were inspected. HEAD was `d78c4be Complete Milestone 7 secure project management`. Milestone 8 was present as uncommitted changes, including Local Knowledge code and `MILESTONE8_VERIFICATION.md`. Those changes were retained. A plan was provided before editing.

No staging, commits or pushes were performed. No changes were made to `.env`, `.venv`, `venv`, model files or user documents. Existing changes to `.env.example` and other Milestone 8 files were not reverted. The existing interpreter initially failed inside the restricted sandbox; running it with approved external access succeeded, without installing or changing the environment.

## Implementation

- Approved Locations UI: add, remove, open and refresh; approval type selector; identifier, name, full path, availability and type columns.
- Multiple document and project approvals share `ApprovedRoots`. Canonical duplicate paths within an approval type reuse their identifier. Overlapping parent/child approvals remain independent; removal explains this explicitly.
- Version 2 settings persist the complete root map and retired identifiers using a flushed temporary file and atomic replacement. Legacy project settings remain readable. Failed replacement leaves memory and the previous settings intact. Invalid settings fail closed.
- Removal requires a default-No UI confirmation and explicit confirmation at the service boundary. It never deletes source folders or files. Removed identifiers are not reused, including after restart.
- Root and target validation remains mandatory for filesystem, PDF, Knowledge and project operations. Traversal, UNC/device/network paths, symlinks/reparse points, sensitive directories, drive roots, the user profile and repository/ancestors are blocked. Missing/unavailable roots remain visible.
- General document identifiers work with deterministic filesystem commands, PDF discovery and Knowledge indexing. The Knowledge selector updates after location changes or source loading. Project discovery still requires a project approval; launch policy and confirmations are unchanged.
- Location operations use retained workers and existing shutdown/cancellation handling. Management is blocked during listening, speech or active operations. Initial refresh occurs on application startup when wake mode is off; otherwise stop listening and refresh.

## Executed checks

All Python commands used `.\.venv\Scripts\python.exe` without modifying that environment.

| Check | Result |
| --- | --- |
| `-m pytest tests/test_approved_locations.py tests/test_filesystem.py tests/test_documents.py tests/test_knowledge_ui.py -q --tb=short` | 156 passed |
| `-m pytest -q --tb=short` | 796 passed, 1 existing audioop deprecation warning |
| `-m tests.project_startup_smoke` | STARTUP_SMOKE_OK, exit 0 |
| `git diff --check` | Passed, exit 0 |

An initial focused run exposed two existing tests prohibiting Pictures/Videos as direct PDF source identifiers. The implementation was corrected to preserve that restriction; explicit document approval provides the new access path. Subsequent focused and full runs passed.

New tests cover multiple approvals, persistence, legacy migration, duplicate paths, nested roots, confirmation, removal without deletion, identifier retirement, atomic-write failure, missing/corrupt settings, traversal/device/network rejection, simulated symlink escape, cancellation and UI add/list/open/remove/source-selector behavior. Existing security, project, PDF, voice and Knowledge tests ran in the full suite. The smoke test uses temporary settings, no Known Folder sources, an empty audio backend and no real microphone/model operations.

## Limits and manual follow-up

All subfolders are within approval scope subject to existing sensitive-folder exclusions and bounded recursive discovery. This change does not remove depth, time or result limits. Explicitly approve a narrower folder when needed. Overlapping approvals do not act as deny rules: removing one root leaves access through another approved ancestor or child.

Filesystem checks retain the existing limitation against concurrent path replacement by another local process; they are not an OS sandbox. Automated UI verification is offscreen, and symlink escape coverage uses an injected link state. A real Explorer/file-picker interaction and physical drive-disconnection walkthrough have not been performed. No claims of those manual checks are made.
