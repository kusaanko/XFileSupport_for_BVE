set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

default:
    @just --list

[windows]
test *args:
    $testTempRoot = Join-Path ([IO.Path]::GetTempPath()) 'blender-xfilesupport-bve-tests'; $env:TMPDIR = (New-Item -ItemType Directory -Force -Path $testTempRoot -ErrorAction Stop).FullName; uv run --locked python -m pytest -q {{args}}; exit $LASTEXITCODE

[unix]
test *args:
    uv run --locked python -m pytest -q {{args}}

lint:
    uv run --locked ruff check tests

fmt:
    uv run --locked ruff format tests

fmt-check:
    uv run --locked ruff format --check tests

check: lint fmt-check test
