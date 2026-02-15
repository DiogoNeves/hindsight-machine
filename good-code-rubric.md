# Diogo’s “Good Code” Rubric

Optimise for: **clarity, composability, small files, obvious side-effects, validation near types, and safe iteration**.

When writing or editing code: follow this rubric.  
If any rule conflicts with existing repo conventions, prefer the repo.  
If you must violate a rule, do it deliberately and leave a short comment explaining why.  
Return validated domain models from I/O boundaries.  
Keep side-effects in `apps/` or `domains/*/io.*`.  
Keep pure logic in `domains/*/logic.*`.

---

## North Star principles

- **Functional core, imperative shell**: pure computation is separate from I/O and side effects.
- **Small files + domain folders**: structure controls complexity.
- **Validation close to types**: correctness lives in Pydantic/Zod.
- **No premature architecture**: avoid ceremony until it solves a real pain.
- **Explicit side effects**: if it touches network/disk/DB, the name must say so.

---

## ✅ Rules (what “good” looks like)

### 1) Repo and Folder Structure

- Organise **by domain** (auth/, billing/, youtube/, etc.).
- Each domain folder acts like a **mini-library** with a clear API surface.
- `shared/` is allowed but must stay **small and specific**.
- Prefer a **monorepo** with clear top-level separation:

```
apps/
  api/        # Python backend
  web/        # TypeScript frontend
domains/      # Business logic (primarily Python)
shared/       # Small cross-cutting primitives
```

### Dependency Direction (explicit)

- `apps/` may depend on `domains/` and `shared/`.
- `domains/` may depend on `shared/`.
- `shared/` depends on nothing (or extremely little).
- `domains/` must never import from `apps/`.

---

### Monorepo Execution Model

- Tooling and environment setup live at the **top level**.
- One command at the root should run or bootstrap everything.
- You must be able to:
  - Work independently inside `apps/api/` or `apps/web/`.
  - Run all tasks from the root (dev, test, build).
- Python and TypeScript manage dependencies locally.
- Task orchestration (Turbo, justfile, Makefile, etc.) lives at the root.
- No manual multi-step setup required.

---

### 2) File Size

- Prefer files under **400 lines**.
- >200 lines is allowed when:
  - The file is single-responsibility and highly cohesive (e.g. models, mappings).
  - Internal sections are clearly structured.
  - There is a plan to split if it grows further.
- If a file approaches 400 lines, refactor by domain responsibility.

---

### 3) Naming (ruthless and consistent)

Side-effect naming:

- `fetch_*` → network
- `load_*` → disk/DB read
- `save_*` / `write_*` → disk/DB write
- `compute_*` → pure computation

Avoid vague buckets:

- `utils`, `helpers`, `manager`, `misc`, `common`

Pure functions must not hide I/O.

---

### 4) Separate Side Effects from Logic (Critical)

Side-effect code:

- Only performs I/O.
- Returns validated domain models (preferred).
- May return `Raw*` types only if validated immediately.

Logic code:

- Only computes from inputs.
- No network, disk, DB, or global state access.

Structure example:

- `domains/x/models.*` → types + validation
- `domains/x/io.*` → side effects
- `domains/x/logic.*` → computation
- `apps/*` → orchestration, retries, logging, error mapping

---

### 5) Boundaries (define once)

Boundaries are:

- HTTP handlers
- DB adapters
- Queue consumers
- File readers
- CLI input parsing

At boundaries:

- Parse and validate external data.
- Convert into domain models.

Inside domains:

- Assume validated types.
- Use `assert` only for invariants that cannot happen unless there is a bug.

---

### 6) Validation Close to the Type

Prefer Pydantic (Python) / Zod (TS) schemas as validation gates.

```
# domains/billing/models.py
from pydantic import BaseModel, Field

class Money(BaseModel):
    pence: int = Field(ge=0)

class VatRate(BaseModel):
    value: float = Field(ge=0.0, le=1.0)
```

```
# domains/billing/logic.py
from .models import Money, VatRate

def compute_total_with_vat(subtotal: Money, vat: VatRate) -> Money:
    vat_pence = int(round(subtotal.pence * vat.value))
    return Money(pence=subtotal.pence + vat_pence)
```

If floats become problematic for money maths, migrate to `Decimal` or basis points.

---

### 7) Functions First. Classes Only When Needed.

Order of preference:

1. Small composable functions.
2. Module/package as the interface.
3. Class only when it owns configuration/state or a side-effect boundary.

Start simple:

- Logic may initially live inside a small class.
- Extract functions only when reuse or growth creates pressure.
- The class becomes the facade/orchestrator.

```
# domains/youtube/io.py
from dataclasses import dataclass
from pydantic import BaseModel
import httpx

class RetentionPoint(BaseModel):
    t: int
    r: float

class RetentionReport(BaseModel):
    video_id: str
    points: list[RetentionPoint]

@dataclass(frozen=True)
class YouTubeConfig:
    api_key: str
    base_url: str = "https://example"

class YouTubeClient:
    def __init__(self, cfg: YouTubeConfig, http: httpx.AsyncClient):
        self._cfg = cfg
        self._http = http

    async def fetch_retention(self, video_id: str) -> RetentionReport:
        url = f"{self._cfg.base_url}/retention/{video_id}?key={self._cfg.api_key}"
        r = await self._http.get(url, timeout=10)
        r.raise_for_status()
        return RetentionReport.model_validate(r.json())
```

---

### 8) No Global State Unless Wrapped

- Avoid module-level mutable singletons.
- If state is required, wrap it in a class.
- Pass state explicitly.
- Dependency injection is used only when it solves a real seam or testability issue.

---

### 9) Error Handling Contract

- I/O layer raises typed exceptions (or returns Result-style).
- `apps/` maps exceptions to HTTP status codes or CLI exit codes.
- Domain logic avoids catching broad exceptions.
- Never silently swallow errors (`except Exception: return None` is forbidden).

---

### 10) Observability (Lightweight)

- Log at the shell (`apps/`), not inside pure logic.
- Include correlation/request IDs when relevant.
- Keep logs namespaced and separable.

---

### 11) Security Defaults

- No secrets in code or committed files.
- Constrain external inputs (length, characters, size limits).
- Use parameterised queries.
- Avoid unsafe file paths.
- Validate all external data at boundaries.

---

### 12) Testing Philosophy

- Test pure logic with table tests and edge cases.
- Add integration tests where seams are risky.
- Avoid trivial coverage padding.
- Protect behaviour, not implementation details.
- Keep tests simple; avoid large amounts of mocks.
- If external I/O must be exercised, prefer recording tools (e.g. VCR) over heavy mocking.

---

### 13) Tooling Expectations

- Python: uv + ruff + pyright.
- TypeScript: eslint + prettier + reasonably strict tsconfig.

---

### 14) TODOs as Decision Bookmarks

Good:

```
# TODO: If we add retries, ensure idempotency via requestId header.
```

Bad:

```
# TODO: fix
```

---

## ⚠️ Smells

### Structure Smells
- Files drifting toward 500+ lines.
- Domain logic inside `apps/`.
- `shared/` growing without discipline.

### Design Smells
- Early DI frameworks or base-class hierarchies.
- Hidden side effects in “compute” functions.
- Generic abstractions solving hypothetical futures.

### Validation Smells
- Validation scattered across logic.
- External data flowing deep without parsing.

### Testing Smells
- Mock-heavy tests breaking on refactor.
- Tests mirroring implementation.
- Integration tests covering too many responsibilities.

---

## GitHub PR Template Checklist

Include this checklist in the PR description template:

- [ ] File(s) under 400 lines or justified cohesive exception
- [ ] Dependency direction respected
- [ ] Side effects separated from logic
- [ ] I/O returns validated domain models
- [ ] No new vague folders (`utils`, `manager`, `common`)
- [ ] Class exists only because it owns config/state or side effects
- [ ] No global mutable state introduced
- [ ] Errors propagate correctly and are mapped at the shell
- [ ] Tests are simple and avoid heavy mocking
- [ ] Tests cover real edge cases or risky seams
- [ ] TODOs include a trigger and a decision bookmark
