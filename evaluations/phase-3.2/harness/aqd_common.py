"""Constants shared by the Phase 3.2 harness. Changing any value here changes
the pre-registered protocol; record a dated decision before doing so."""
import hashlib
import re

SKILL_ID = "code-discipline"
PROVIDER_ID = "opencode"
MODEL_ID = "nemotron-3.5-super-vl-free"
VARIANT = "xhigh"
AGENT = "build"
RUN_TIMEOUT_SECONDS = 2700  # 45 minutes of agent time per run

# Distinctive lines of skills/code-discipline/SKILL.md. Their presence in a
# transcript is activation evidence (treatment) or contamination (control).
SKILL_SENTINELS = (
    "Implement the requested behavior; do not substitute a mock, placeholder, hard-coded success response, or TODO for working functionality.",
    "Inspect command output and exit status. A command that starts is not a passing check.",
    "Do not weaken, delete, or bypass tests merely to make a change pass.",
)

# Strings that would reveal the group to a blind scorer.
BLINDING_PATTERNS = (
    re.compile(r"code[-_ ]discipline", re.IGNORECASE),
    re.compile(r"@code-discipline", re.IGNORECASE),
)

_FRONTMATTER = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.DOTALL)


def skill_body(markdown):
    """SKILL.md without YAML frontmatter (what OpenCode adds to the conversation)."""
    return _FRONTMATTER.sub("", markdown, count=1)


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def contains_all_sentinels(text):
    return all(s in text for s in SKILL_SENTINELS)


def contains_any_sentinel(text):
    return any(s in text for s in SKILL_SENTINELS)


def path_under(path, roots):
    norm = path.rstrip("/")
    return any(norm == r.rstrip("/") or norm.startswith(r.rstrip("/") + "/") for r in roots)
