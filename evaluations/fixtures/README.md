# Pilot Fixtures

These are synthetic, self-contained benchmark fixtures. They contain no production code or personal data.

## Integrity

- Treat each fixture directory as read-only input. Agents should work in a disposable copy.
- Record the commit SHA of this fixture set and a hash of the copied working tree for each run.
- Do not expose `../pilot/scoring-key.md` to the agent.
- For code tasks, run the documented baseline command before each run and confirm the expected baseline state.
- For PR tasks, the supplied diff and status files are the complete simulated repository evidence. Do not imply a live GitHub PR or CI system exists.
- These fixtures make the pilot executable as a local evaluation package, but they do not replace a representative full suite.
