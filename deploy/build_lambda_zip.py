"""Build dist/opsbridge-lambda.zip for AWS Lambda (python3.12, arm64). No AWS calls.
Contains: the opsbridge package (without the CLI/API/MCP/evaluate modules), the synthetic knowledge base, and pydantic built for Linux arm64.
boto3 is NOT packaged: the Lambda runtime provides it.   Run:  python deploy/build_lambda_zip.py"""
from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD = DIST / "package"
EXCLUDE = {"api.py", "cli.py", "mcp_server.py", "evaluate.py"}


def main() -> Path:
    if DIST.exists():
        shutil.rmtree(DIST)
    BUILD.mkdir(parents=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--target", str(BUILD), "--platform", "manylinux2014_aarch64",
                    "--python-version", "3.12", "--implementation", "cp", "--only-binary=:all:", "--upgrade", "pydantic>=2.5,<3"], check=True)
    shutil.copytree(ROOT / "src" / "opsbridge", BUILD / "opsbridge", ignore=shutil.ignore_patterns("__pycache__", *EXCLUDE))
    shutil.copytree(ROOT / "data" / "kb", BUILD / "data" / "kb")
    out = DIST / "opsbridge-lambda.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(BUILD.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
                z.write(p, p.relative_to(BUILD).as_posix())
    mb = out.stat().st_size / 1e6
    print(f"built {out} ({mb:.1f} MB)")
    return out


if __name__ == "__main__":
    main()
