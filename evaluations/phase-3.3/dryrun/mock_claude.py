#!/usr/bin/python3
"""MOCK `claude` for the no-model-call dry run of launch-run-cc.sh. NOT Claude Code.

It never contacts any network host. It answers `--version` and `auth status --json`, and for `-p` it:
  1. records what the launcher actually handed it (argv, working directory, OS user, environment NAMES, whether the
     synthetic token arrived and matches, the prompt's SHA-256), and probes isolation from inside the agent's uid
     (can it write immutable files, replace the skills directory, read the operator store or the other arm, read
     the token through /proc from a child process);
  2. edits the one mutable SMOKE file, as an agent would;
  3. replays a SYNTHETIC stream-json transcript in the init shape the REAL 2.1.330 CLI emits (observed offline
     against a local mock API, phase-3.3/boundary): the real working directory, the plugin given with --plugin-dir
     and the skills it really contains ("aqd-arm:<name>", plus the built-in "doctor"), permissionMode "default",
     served_by_anthropic true; unless the scenario deliberately falsifies a field.

The scenario comes from scenario.json next to this file (root-owned; written by dryrun-cc.sh). The token's value is
never printed: only "present"/"matches" booleans. The probe is emitted as a system event of subtype "mock_probe",
which cc_adapter.analyse_transcript ignores (a real CLI never emits it).
"""
import hashlib
import json
import os
import pwd
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
SCENARIO, TOKEN_OK = {}, False


def load_scenario():
    global SCENARIO, TOKEN_OK
    SCENARIO = json.load(open(os.path.join(HERE, "scenario.json"), encoding="utf-8"))
    TOKEN_OK = bool(TOKEN) and hashlib.sha256(TOKEN.encode()).hexdigest() == SCENARIO["token_sha256"]


def emit(event):
    print(json.dumps(event), flush=True)


def can(fn):
    try:
        fn()
        return True
    except OSError:
        return False


def readable(path):
    return can(lambda: os.listdir(path) if os.path.isdir(path) else open(path, "rb").close())


def probe():
    config = os.environ.get("CLAUDE_CONFIG_DIR", "")
    skills = os.path.join(config, "skills")
    child_env = subprocess.run(["/bin/sh", "-c", "env"], capture_output=True, text=True).stdout
    # what an agent's Bash tool could do: read the parent (claude) process environment through /proc
    via_proc = subprocess.run(["/bin/sh", "-c", 'cat /proc/$PPID/environ 2>/dev/null | tr "\\0" "\\n"'],
                              capture_output=True, text=True).stdout
    tmp_hits = []
    for root in {os.environ.get("TMPDIR", "/tmp"), "/tmp", "/var/tmp", "/dev/shm"}:
        for directory, _, names in os.walk(root):
            for name in names:
                try:
                    with open(os.path.join(directory, name), "rb") as handle:
                        if TOKEN and TOKEN.encode() in handle.read():
                            tmp_hits.append(name)
                except OSError:
                    pass
    plugin = sys.argv[sys.argv.index("--plugin-dir") + 1] if "--plugin-dir" in sys.argv else "/nonexistent"
    renamed = can(lambda: os.rename(skills, skills + ".moved"))
    if renamed:
        os.rename(skills + ".moved", skills)
    return {
        "argv_matches_expected": sys.argv[1:] == SCENARIO["expected_argv"],
        "cwd": os.getcwd(),
        "user": pwd.getpwuid(os.getuid()).pw_name,
        "env_names": sorted(os.environ),
        "token_present": bool(TOKEN),
        "token_matches": TOKEN_OK,
        "prompt_sha256": hashlib.sha256(PROMPT).hexdigest(),
        "can_write_TASK_md": os.access("TASK.md", os.W_OK),
        "can_write_notes_txt": os.access("notes.txt", os.W_OK),
        "can_create_in_skills": can(lambda: open(os.path.join(skills, "planted.md"), "w").close())
        or can(lambda: open(os.path.join(plugin, "skills", "planted.md"), "w").close()),
        "can_rename_arm_plugin": can(lambda: os.rename(plugin, plugin + ".moved")),
        "can_rename_skills_dir": renamed,
        "can_create_in_config_dir": can(lambda: open(os.path.join(config, ".mock-state"), "w").close()),
        "skills_dir_listing": sorted(os.listdir(skills)) if os.path.isdir(skills) else None,
        "can_read_operator_store": readable(SCENARIO["operator_dir"]),
        "can_read_other_arm": readable(SCENARIO["other_env_dir"]),
        "can_read_checkout": readable(SCENARIO["checkout"]),
        "can_read_root_home": readable("/root"),
        "token_in_child_env": bool(TOKEN) and TOKEN in child_env,
        "token_readable_via_proc_parent_environ": bool(TOKEN) and TOKEN in via_proc,
        "token_in_temp_files": tmp_hits,
    }


def main():
    args = sys.argv[1:]
    if args == ["--version"]:
        print("2.1.330 (Claude Code)")
        return 0
    load_scenario()
    if args == ["auth", "status", "--json"]:
        auth = SCENARIO.get("auth") or {"loggedIn": True, "authMethod": "oauth_token", "apiProvider": "firstParty",
                                        "subscriptionType": "max"}
        print(json.dumps(auth if TOKEN_OK else {"loggedIn": False, "authMethod": "none"}))
        return 0 if TOKEN_OK else 1
    global PROMPT
    PROMPT = sys.stdin.buffer.read()
    s = SCENARIO
    model = s["model"]
    plugin = args[args.index("--plugin-dir") + 1] if "--plugin-dir" in args else "/nonexistent"
    skills_dir = os.path.join(plugin, "skills")
    real_skills = sorted(n for n in (os.listdir(skills_dir) if os.path.isdir(skills_dir) else [])
                         if os.path.isfile(os.path.join(skills_dir, n, "SKILL.md")))
    listed = sorted([f"aqd-arm:{n}" for n in real_skills] + ["doctor"])
    emit({"type": "system", "subtype": "mock_probe", "probe": probe()})
    init = {"type": "system", "subtype": "init", "session_id": "mock-session", "uuid": "u0", "apiKeySource": "none",
            "claude_code_version": "2.1.330", "cwd": os.getcwd(), "model": s.get("init_model", model),
            "tools": ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "Skill"], "mcp_servers": [],
            "permissionMode": "default", "served_by_anthropic": True, "slash_commands": listed + ["clear"],
            "output_style": "default", "skills": listed,
            "plugins": [{"name": "aqd-arm", "path": plugin, "source": "aqd-arm@inline", "version": "1.0.0"}]}
    init.update(s.get("init_overrides") or {})
    emit(init)
    if s.get("background_child"):  # a leftover process in the session's group, as a Bash tool job would be
        subprocess.Popen(["/bin/sh", "-c", "trap '' TERM; sleep 300"], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL)  # ignores TERM: only KILL (or the launcher) ends it
    if s.get("sleep"):
        emit({"type": "assistant", "message": {"model": model, "role": "assistant",
                                               "content": [{"type": "text", "text": "Working."}]}})
        time.sleep(s["sleep"])
    if s.get("corrupt"):
        print("{this is not json", flush=True)
    blocks = [{"type": "text", "text": "I will update notes.txt."}]
    if s.get("invoke_skill") and "code-discipline" in real_skills:
        blocks.append({"type": "tool_use", "id": "t0", "name": "Skill", "input": {"skill": "code-discipline"}})
    blocks.append({"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "notes.txt"}})
    if s.get("sandbox_fail"):  # the real 2.1.330 answer to every Bash call when namespaces are refused
        blocks.append({"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "python3 -m pytest"}})
    emit({"type": "assistant", "message": {"model": s.get("turn_model", model), "role": "assistant", "content": blocks}})
    with open("notes.txt", "a", encoding="utf-8") as handle:
        handle.write("mock edit\n")
        if s.get("leak_token"):
            handle.write(TOKEN + "\n")  # a deliberate leak into a captured file
    emit({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}})
    if s.get("sandbox_fail"):
        emit({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t2", "is_error": True,
             "content": "Exit code 1\nbwrap: No permissions to create new namespace, likely because the kernel does "
                        "not allow non-privileged user namespaces."}]}})
    emit({"type": "assistant", "message": {"model": model, "role": "assistant",
                                           "content": [{"type": "text", "text": "Done."}]}})
    subtype, is_error = s.get("result", ["success", False])
    emit({"type": "result", "subtype": subtype, "is_error": is_error, "num_turns": 2, "session_id": "mock-session",
          "total_cost_usd": 0.0, "usage": {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0,
                                           "cache_creation_input_tokens": 0},
          "modelUsage": {model: {"inputTokens": 1}}})
    return s.get("exit", 0)


if __name__ == "__main__":
    sys.exit(main())
