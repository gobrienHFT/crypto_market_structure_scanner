# Security and Release Notes

The scanner reads exchange, explorer, Discord, and optional trading credentials
from the local `.env` file. `.env` is ignored by Git. `.env.example` contains
blank placeholders only.

Run the current-tree audit before publishing:

```powershell
python scripts/security_audit.py
```

The current tracked tree is expected to report no credential assignments. An
optional history check is advisory:

```powershell
python scripts/security_audit.py --history
```

The history advisory currently reports that an explorer key was present in an
old commit. That key should be rotated before any public release. Removing or
rewriting historical commits is intentionally not performed automatically,
because it changes collaborators' Git history and requires an explicit release
decision.

Live execution is separate from the research radar. The radar, offline replay,
and Discord alerts do not place orders. Any execution connector must fail closed
when credentials, position state, timestamps, or risk limits are unavailable.
