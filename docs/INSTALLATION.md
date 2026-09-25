# Reproducible installation and verification

The supported full application setup is a **source checkout with an editable Python installation and a built frontend**. It runs on Windows or Linux and binds only to localhost. The offline starter workspace requires no model credentials, GPU, or model download.

Use **Python 3.12**, **Node.js 24**, and **pnpm 11.19.0** for the documented/CI path. Python 3.12 or later is declared by the package, but a newer interpreter is not a substitute for running the checks. An initial dependency install requires internet access; the seeded offline workspace works afterward without a network connection.

## Windows PowerShell

Open PowerShell in your copy of the repository. These commands use the virtual environment directly, so no PowerShell activation policy change is needed.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
npm install --global pnpm@11.19.0
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
.\.venv\Scripts\jev-scout.exe serve
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). Keep the terminal open while using the app; Ctrl+C stops the server. If the Python launcher `py` is unavailable, use the full path to your Python 3.12 executable for the first command.

To verify the checkout:

```powershell
.\.venv\Scripts\python.exe scripts\verify.py --require-frontend --package
```

## Linux

Your Python installation must include `venv`/`ensurepip`. On distributions that split them into a separate system package, install that package using your normal package manager first. Run the following from the repository root:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
npm install --global pnpm@11.19.0
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
.venv/bin/jev-scout serve
```

Use a user-owned Node installation if global npm installation would otherwise require elevated permissions. Open [http://127.0.0.1:8765](http://127.0.0.1:8765), then verify with:

```bash
.venv/bin/python scripts/verify.py --require-frontend --package
```

## What is pinned

| File | Scope |
| --- | --- |
| `requirements.lock` | Exact core Python runtime dependency closure, with the Windows-only `colorama` marker |
| `requirements-dev.lock` | Includes the core lock and pins test, lint, and build tools |
| `frontend/pnpm-lock.yaml` | Frontend dependency resolution and package integrity metadata; use frozen installs |
| `pyproject.toml` | Direct project requirements and exact setuptools/wheel build requirements |

Install a lock first, then the project with `--no-deps`; this avoids silently resolving a different dependency set. The development instructions also use `--no-build-isolation` because the matching build tools are already installed by the development lock. For a runtime-only installation, install `requirements.lock`, then `pip install --no-deps -e .`; that command creates an isolated environment with the pinned build requirements.

Python locks contain exact version pins, not artifact hashes. They are a reproducible version resolution for the supported environment, not a hermetic or independently audited supply-chain manifest. OS packages, interpreter patch versions, action tags, and Docker base image tags can still change. The optional `local` GPU/model dependencies are deliberately outside the core locks: PyTorch packages depend on the selected platform/accelerator. Follow the main README for the local-model path rather than installing it just to open the workspace.

When updating dependencies, update the relevant lock deliberately, install into a fresh environment, and rerun verification. Do not replace the lock with an unrestricted `pip freeze` containing editable absolute paths or machine-specific model packages.

## Verification and CI

`scripts/verify.py` can be run from any directory and always checks this repository. It runs dependency consistency, Ruff, backend tests, then frontend typecheck, unit tests, and a production build when frontend dependencies are available. `--require-frontend` makes missing frontend prerequisites a failure. `--skip-frontend` is an explicit backend-only check, and reports that frontend checks were skipped.

`--package` additionally builds a real wheel, installs it into a new temporary virtual environment without runtime dependencies, and imports it with Python isolated mode from outside the checkout. It verifies all 20 attributed papers, three profiles, and a real 60-pair offline benchmark from the installed wheel. It also checks that the wheel excludes `.env` and the runtime database. The isolated fixture/benchmark smoke check needs no model library or provider call.

The GitHub workflow runs the source-install checks on Windows and Linux with Python 3.12/Node 24, and runs a Linux Docker smoke job. CI requires no secrets. The offline benchmark generated by CI is uploaded as an artifact with quality metrics explicitly unavailable while labels are absent. A committed workflow is a check definition; its GitHub run is only available after you push the repository yourself.

## Wheel scope

The wheel supports the Python core and offline benchmarking. It installs the single source of public fixture data under the environment's `share/jev-scout/data` directory, and the loader locates it via `sysconfig`; it never depends on the caller's current directory. The wheel does **not** bundle the React production build or a relocatable application workspace. Use the source-install instructions above for the complete UI/server. Do not present `pip install` of the wheel alone as a complete desktop installation.

To build the Python wheel directly after installing the development lock:

```console
python -m build --wheel --no-isolation
```

## Optional Linux container

The Dockerfile builds the frontend in one stage and serves the application as an unprivileged user in a Python runtime stage. It does not include model weights, secrets, or your runtime database. A named volume persists the local database.

The application intentionally binds to `127.0.0.1`. On a **Linux Docker host**, use host networking so the host browser can reach that loopback listener:

```bash
docker build --tag jev-scout:local .
docker run --rm --name jev-scout --network host --mount source=jev-scout-data,target=/app/runtime jev-scout:local
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765) on the Linux host. Do not add a `-p` mapping or change the binding to `0.0.0.0`: ordinary Docker port mapping does not reach a loopback-bound server inside a bridged container. This image is not a public hosting recipe. Keep the source-install path for Windows/macOS Docker Desktop unless you separately verify a supported host-network arrangement.

The development machine had the Docker CLI but **no running Docker engine**, so image build/run could not be validated there. The Linux CI job is configured to build the image and verify both health and the built frontend; do not claim that job passed before its actual run. Local source/wheel verification is separate from Docker verification.

## Configuration and data

The `.env` file is optional for offline use. Copy `.env.example` only if you want to configure a provider or override a setting, and leave it untracked. Never put a secret in frontend configuration or a repository file. A key being absent should leave the offline baseline usable.

The source setup stores state in `runtime/` by default. Back up the database with the provided `jev-scout backup` command, and retain the virtual environment/dependency locks needed to reproduce your installation. Rebuilding the frontend does not require deleting reading notes or the database.

If the server responds with an API-only message instead of the UI, run the frontend build from the source checkout and restart the server. If port 8765 is already occupied, use `jev-scout serve --port 8767` and open the corresponding loopback URL. Live provider verification is a separate step from these offline install checks.
