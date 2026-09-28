# Environment Loading — how credentials become available

**Status:** documented, **not changed.** The brief asked for this to be recorded before
any provider work, and for cleanup to be proposed separately rather than mixed into the
failover validation. This document is that record.

## The short version

`Settings` reads `.env` into a Python object. It does **not** export anything to
`os.environ`. On the LiteLLM path, credentials reach the provider SDK as a **side effect of
`import litellm`**, which calls `load_dotenv()` at module import.

## Verified sequence

| Step | What happens | Where |
|---|---|---|
| 1 | `Settings()` is constructed; `.env` is parsed into the object | `config.py:18-23` (`env_file=PROJECT_ROOT/".env"`) |
| 2 | `settings.gemini_api_key` / `settings.openai_api_key` are readable | — |
| 3 | `os.environ` is still **untouched** | verified: `GEMINI_API_KEY in os.environ` → `False` |
| 4 | `import litellm` runs `load_dotenv(override=...)` | `litellm/__init__.py:30` |
| 5 | `.env` values now appear in `os.environ` | verified: `GEMINI_API_KEY in os.environ` → `True` |
| 6 | The provider SDK reads the credential from the process environment | `google-genai` / `openai` read `os.environ` |

**Verified directly:**

```text
control (rla code only):        'GEMINI_API_KEY' in os.environ  ->  False
after `import litellm`:         'GEMINI_API_KEY' in os.environ  ->  True
```

## Why it behaves differently per backend

| Backend | How the key reaches the provider |
|---|---|
| `gemini` (native) | **Explicit.** `genai.Client(api_key=settings.gemini_api_key)` — our code passes the value. `store/cache.py:...` no; `llm/gemini.py:95`. |
| `litellm` | **Implicit.** LiteLLM resolves the credential itself from the process environment, which is populated by its own `load_dotenv()` at import. |

Both work. Only the LiteLLM path depends on a library's import side effect.

## Why this is worth knowing (and why it was left alone)

The two orderings are not equivalent, and the difference is invisible:

- **Who populates the environment.** On the LiteLLM path, a third-party library mutates
  global process state as a side effect of being imported. Our code never asked for that.
- **When.** Only on first LiteLLM import. A capability probe, a CLI `--help` path, or a
  test that touches `litellm_backend` would trigger it earlier than the provider call that
  actually needs it.
- **Precedence.** `load_dotenv(override=...)` depends on a library-internal setting. If it
  overrides, a stray shell variable can silently win over `.env`.

### A CWD sensitivity I suspected and then disproved

I expected `load_dotenv()` to resolve relative to the CWD and therefore to fail when
`rla` is run from a subdirectory. **It does not.** Verified with LiteLLM imported from
both directories:

```text
repo root:   'GEMINI_API_KEY' in os.environ  ->  True
from src/:   'GEMINI_API_KEY' in os.environ  ->  True
```

python-dotenv's `find_dotenv()` walks up from the CWD until it locates a `.env`, so the
project root is found either way. The CWD risk is recorded here as **disproved**, because
it is a plausible-sounding hazard worth not re-investigating.

## Proposed cleanup — NOT applied

Offered separately, as instructed. Nothing below has been implemented.

**Option A — make it explicit in one place (recommended).**
Call `load_dotenv(PROJECT_ROOT / ".env", override=False)` in `rla.config` at import time,
so credential availability does not depend on which library happens to be imported. The
LiteLLM side effect becomes redundant rather than load-bearing. Small, behaviour-preserving
in intent, and it removes the CWD sensitivity.

**Option B — pass credentials explicitly to LiteLLM.**
`litellm.completion(api_key=...)` per call, reading from `Settings`. Removes all reliance
on the process environment, at the cost of threading the right key per provider through
the backend. More explicit, slightly more code, and it makes "which key served this call"
answerable from the call site.

**Option C — do nothing.**
Defensible today: one provider, one path, the behaviour is verified working, and the CWD
hazard was checked and disproved. The remaining cost is a latent reliance on a library's
import side effect, plus the `override` precedence question.

**Recommendation:** A now, B if a second provider lands, C is acceptable only while there
is exactly one configured provider and all commands are run from the repo root.

## Verification after any change

```powershell
# must print True after the change
.\.venv\Scripts\python.exe -c "import litellm, os; print('key in env:', 'GEMINI_API_KEY' in os.environ)"

# and must still print True from a subdirectory (already true today)
Push-Location src
..\.venv\Scripts\python.exe -c "import litellm, os; print('key in env:', 'GEMINI_API_KEY' in os.environ)"
Pop-Location
```
