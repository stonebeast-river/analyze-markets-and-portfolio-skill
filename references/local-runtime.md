# Runtime setup

Use an isolated Python environment for the bundled tools. Python 3.12 was used for the recorded release checks. Keep configuration, databases, document downloads, response archives and private portfolio files outside the installed skill.

From the repository or installed skill root:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r scripts/requirements-optional.txt
.venv/Scripts/python.exe -B scripts/market_engine.py init-config --config <external-runtime>/market-config.json
.venv/Scripts/python.exe -B scripts/market_engine.py --db <external-runtime>/research.sqlite3 health
```

On macOS/Linux, use `.venv/bin/python` instead. The core command interface uses the standard library; collection modes may need the dependencies in `scripts/requirements-optional.txt`. Optional registered providers read credentials from process environment variables. A configured provider is not proof of current access.

`init-config` creates a research starter, not a portfolio. Configure the requested instruments, provider scope and external database deliberately. `research-stock`, `research-fund`, `research-opportunities`, `research-chips` and their verification routes provide evidence for independent analysis. Use `--help` for each command's options. Request-specific source health and freshness must be checked at research time.

No account, holdings, automation or machine-specific runtime configuration is bundled. See [data-engine.md](data-engine.md) and [provider-registry.md](provider-registry.md) for command contracts and source boundaries.
