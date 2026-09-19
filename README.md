# NextAppStore Verification Harness

This harness provides an isolated, reproducible Docker sandbox for running linters, database migrations, tests, and agent-generated commands without risking host machine pollution.

## Architecture

- **`Dockerfile.sandbox`**: Container image definition with Ubuntu 24.04, Python venv, Poetry, PostgreSQL, Terraform, and Shellcheck.
- **`verify.sh`**: The verification script that boots Postgres, seeds the test database, runs `ruff`, validates templates, and executes `pytest`.
- **`sandbox.py`**: The Python sandbox runner and programmatic SDK (`run_in_sandbox`).
- **`run.sh`**: Quick bash CLI wrapper.

---

## How to Use

### 1. Command Line (Developers & Agents)

From anywhere in the repository root:

```bash
# 1. Fast verification (Linting + Unit tests)
python3 agentic-harness/sandbox.py --fast
# Or via bash wrapper:
./agentic-harness/run.sh --fast

# 2. Full verification (Linting + Integration + Unit tests)
python3 agentic-harness/sandbox.py --full

# 3. Ephemeral mode (Copies repo to isolated tempdir, guarantees zero host pollution)
python3 agentic-harness/sandbox.py --ephemeral --fast

# 4. Run any custom command inside the container
python3 agentic-harness/sandbox.py pytest backend/tests/unit/test_models.py
python3 agentic-harness/sandbox.py ruff check backend/

# 5. Force rebuild the sandbox image
python3 agentic-harness/sandbox.py --rebuild
```

---

### 2. Programmatic Python SDK (Agent Loops & Eval Scripts)

You can import `run_in_sandbox` directly in agent workflows or benchmark scripts:

```python
from sandbox import run_in_sandbox

# Execute a test run
result = run_in_sandbox(
    command="bash agentic-harness/verify.sh fast",
    timeout=180,
    ephemeral=True,  # Protect host workspace
)

if result.success:
    print("Verification succeeded!")
else:
    print(f"Failed with exit code {result.exit_code}")
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
    # Feed result.stderr / result.stdout back to the LLM for self-correction
```

### Docs for the Presentation

```mermaid
---
title: Agent Verification Loop
---


flowchart TD
    Agent["Coding Agent"] -->|"1. Triggert Testlauf"| Runner["Runner (sandbox.py)"]
    Runner -->|"2. Isoliert Workspace"| Docker["Docker-Sandbox\n Linting + Verfication + Testing"]
    Docker -->|"3. Liefert Fehlerlogs"| Agent
```

```mermaid
---
title: Context Engineering - Statischer Kontext
---
flowchart

	subgraph NextAppStore - Github Org

		ga[AGENTS.md]

		subgraph Core Application
			subgraph frontend
				fa[AGENTS.md]
			end
			subgraph backend
				ba[AGENTS.md]
				openapi[openapi.json]
			end

			subgraph worker
				wa[AGENTS.md]
			end
		end
		subgraph template-app
			aa[AGENTS.md]
		end
		subgraph deployment
			da[AGENTS.md]
		end
	end

	subgraph externe Quellen
		ltidocs[LTI 1.3 Spezifikation]
	end

	%% general agent.md verweist auf die agent.md der einzelnen Repositorys
	ga-->fa
	ga-->ba
	ga-->aa
	ga-->wa
	ga-->da

	%% backend und frontend teilen den Zugriff auf die OpenAPI spezifikation
	fa-->openapi
	ba-->openapi

	%% Zugriff auf externe Doku
	ba-->ltidocs

```

### Notes

- MCP Server refernziern
