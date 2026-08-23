# VoxPilot AI project rules

- Target Windows 11 and require Python 3.12.
- Use no paid APIs or API keys; prefer local-first processing.
- Never execute arbitrary commands. Every tool and application must be allowlisted.
- Sensitive actions require explicit approval in future milestones.
- Destructive actions are prohibited until explicitly designed and implemented.
- Never modify `.venv`.
- Add tests for every new tool.
- Keep business logic separate from UI code.
- Keep Windows-specific behavior behind interfaces.
- Never claim a test passed unless it actually ran successfully.

