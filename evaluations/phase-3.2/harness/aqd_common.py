"""Constants shared by the Phase 3.2 harness. Changing any value here changes
the pre-registered protocol; record a dated decision before doing so."""
import hashlib
import re

SKILL_ID = "code-discipline"
AGENT = "build"
RUN_TIMEOUT_SECONDS = 2700  # 45 minutes of agent time per run

# Models are not constants: every scheduled run names its model as
# "provider/model" or "provider/model#variant" (OpenCode's selector syntax).
# Only Claude (provider "anthropic") and Grok (provider "xai") are in scope.
ALLOWED_PROVIDERS = ("anthropic", "xai")
_MODEL_REF = re.compile(r"^(?P<provider>[a-z0-9-]+)/(?P<model>[A-Za-z0-9._:-]+)(?:#(?P<variant>[A-Za-z0-9._-]+))?$")


def parse_model(ref):
    """Return (provider, model, variant or None). Raises ValueError for anything else."""
    match = _MODEL_REF.match(ref or "")
    if not match:
        raise ValueError(f"model reference must be provider/model[#variant], got {ref!r}")
    if match.group("provider") not in ALLOWED_PROVIDERS:
        raise ValueError(f"provider {match.group('provider')!r} is out of scope; allowed: {ALLOWED_PROVIDERS}")
    return match.group("provider"), match.group("model"), match.group("variant")

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
