# Running the pilot fixtures

## Prepare

1. Check out this branch and record its commit SHA.
2. Copy one fixture directory to a fresh temporary workspace for each run. Never reuse a modified workspace.
3. Record a SHA-256 manifest of the copied fixture files, the agent/model version, tool permissions, skill revision, and activation result.
4. Keep the evaluator key out of the agent context.
5. Randomize whether the control or treatment run happens first.

## Code tasks

From the copied task directory, run the baseline command in its README before starting the agent. CD-03 intentionally has a failing baseline: the empty timezone input fails, and a separate legacy test is also known to fail. The agent must not modify the unrelated legacy test or misreport the baseline.

After the agent finishes, run the same focused and full test commands, inspect the complete diff, and compare it with the task's hard constraints.

## Writing and source tasks

Supply the corresponding `input.md` or `evidence.md` exactly as written. The prompt itself is in `../pilot/tasks.md`. Do not add facts, sources, or hidden context in either condition.

## PR tasks

Supply all files in the task's PR fixture directory. The evidence is simulated; there is no live PR, CI, or repository state. Score the agent on whether it accurately inspects and reports the supplied evidence and respects the explicit no-action boundaries.

## Output capture

Save the complete prompt, transcript, final response, changed files/diff (if any), command outputs, elapsed time, tool-call count where available, and a blind run ID. Record treatment condition separately from the reviewer packet.
