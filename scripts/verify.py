"""Run repository checks without model keys; optionally smoke-test a built wheel.

Use the repository's virtual-environment Python, then run this script from any
working directory. Frontend checks run when dependencies are installed; CI uses
--require-frontend so a missing frontend cannot count as a successful check.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, cwd: Path = ROOT, env: dict | None = None) -> None:
    print(f"\n> {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def verify_wheel() -> None:
    """Import real fixture data from an installed wheel outside the checkout."""
    with tempfile.TemporaryDirectory(prefix="jev-scout-wheel-") as temporary:
        work = Path(temporary)
        wheels = work / "wheels"
        run([sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(wheels)])
        distributions = list(wheels.glob("jev_scout-*.whl"))
        if len(distributions) != 1:
            raise RuntimeError("Expected exactly one Jev Scout wheel")
        wheel = distributions[0]
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            for filename in ("papers.json", "profiles.json", "annotations.template.json"):
                if not any(name.endswith(f"share/jev-scout/data/{filename}") for name in names):
                    raise RuntimeError(f"Required data is missing from wheel: {filename}")
            if any(Path(name).name == ".env" or "scout.sqlite3" in name for name in names):
                raise RuntimeError("Private runtime data must never be packaged")
        environment = work / "isolated"
        venv.EnvBuilder(with_pip=True).create(environment)
        executable = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run([str(executable), "-m", "pip", "install", "--no-deps", "--no-index", str(wheel)], cwd=work)
        # -I ignores PYTHONPATH and the checkout; dependencies are deliberately
        # absent, verifying that fixture loading and offline metrics stand alone.
        smoke = """
import asyncio
import json
import sys
from pathlib import Path
import jev_scout
from jev_scout.fixtures import data_directory, load_papers, load_profiles
from jev_scout.evaluation import benchmark
assert Path(jev_scout.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
papers, profiles = load_papers(), load_profiles()
assert len(papers) == 20 and len(profiles) == 3
report = asyncio.run(benchmark())
assert report['dataset']['pairs'] == 60
assert report['quality_evaluated'] is False
assert len(report['methods']) == 3
print(json.dumps({'wheel_import': str(jev_scout.__file__), 'fixture_directory': str(data_directory()), 'papers': len(papers), 'profiles': len(profiles), 'measured_pairs_per_method': 60}))
"""
        run([str(executable), "-I", "-c", smoke], cwd=work)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    frontend = parser.add_mutually_exclusive_group()
    frontend.add_argument(
        "--require-frontend", action="store_true", help="Fail if frontend prerequisites are missing"
    )
    frontend.add_argument("--skip-frontend", action="store_true", help="Run only backend checks")
    parser.add_argument(
        "--package",
        action="store_true",
        help="Build a wheel and run its fixtures/benchmark in a clean environment",
    )
    arguments = parser.parse_args(argv)
    if sys.version_info < (3, 12):  # noqa: UP036 - this script can run before the project is installed
        parser.error("Python 3.12 or later is required")
    try:
        run([sys.executable, "-m", "pip", "check"])
        run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "src",
                "tests",
                "scripts",
                "data/refresh_public_collection.py",
            ]
        )
        run([sys.executable, "-m", "pytest", "-q"])
        if arguments.skip_frontend:
            print("\nFrontend checks explicitly skipped.", flush=True)
        else:
            pnpm = shutil.which("pnpm")
            has_modules = (ROOT / "frontend" / "node_modules").is_dir()
            if not pnpm or not shutil.which("node") or not has_modules:
                message = "Frontend prerequisites missing: install Node.js, pnpm, and run pnpm --dir frontend install --frozen-lockfile."
                if arguments.require_frontend:
                    raise RuntimeError(message)
                print(f"\nSKIPPED frontend: {message}", flush=True)
            else:
                for task in ("typecheck", "test", "build"):
                    run([pnpm, "--dir", str(ROOT / "frontend"), task])
        if arguments.package:
            verify_wheel()
    except (subprocess.CalledProcessError, OSError, RuntimeError) as error:
        print(f"\nVerification failed: {error}", file=sys.stderr, flush=True)
        return 1
    print("\nAll requested checks passed. No model API credentials or model downloads were used.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
