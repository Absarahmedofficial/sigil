"""Top-level CLI for PyGlimmer-Toolkit.

Built on Typer + Rich. Three subcommands matching the three pillars:
    pyglimmer pyarmor    PyArmor-protected scripts
    pyglimmer dotnet     .NET assemblies (ConfuserEx, etc.)
    pyglimmer python    Generic Python obfuscation (base64/marshal/lambda chains)

Plus a `pipeline` subcommand that runs all applicable pillars on a target.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel

from pyglimmer_toolkit import __version__

app = typer.Typer(
    name="sigil",
    help="Sigil: generic Python obfuscation stripper with optional LLM cleanup. v1 ships one pillar; .NET and PyArmor support deferred to v2.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
)

console = Console(stderr=True)
# A separate Console for stdout is conventional for tools that may be piped.
import sys as _sys
stdout_console = Console(file=_sys.stdout)

# Subcommand groups (v1: one pillar — the generic Python stripper)
python_app = typer.Typer(help="Strip layers from obfuscated Python.", no_args_is_help=True)
pipeline_app = typer.Typer(help="Run the stripper pipeline on a target.", no_args_is_help=True)

# NOTE: `pyarmor` and `dotnet` subcommand groups were DEFERRED TO v2 per
# 05_ADVERSARIAL_REVIEW.md section 4.3. They are NOT registered here in v1.
# Re-add them in v2 when the corresponding modules are implemented.

app.add_typer(python_app, name="python")
app.add_typer(pipeline_app, name="pipeline")


def _version_callback(value: bool) -> None:
    """Print version and exit when --version is passed."""
    if value:
        stdout_console.print(f"pyglimmer-toolkit {__version__}")
        raise typer.Exit(code=0)


@app.callback()
def main_callback(
    version: Annotated[
        Optional[bool],
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Print version and exit.",
        ),
    ] = None,
) -> None:
    """PyGlimmer-Toolkit: see subcommands below."""


@app.command()
def hello(
    name: Annotated[str, typer.Argument(help="Name to greet.")] = "world",
) -> None:
    """Print a greeting. (Placeholder command — verify the CLI works.)"""
    console.print(
        Panel(
            f"Hello, [bold cyan]{name}[/bold cyan]! PyGlimmer-Toolkit is wired up.",
            title="pyglimmer hello",
            border_style="cyan",
        )
    )


# ---------------------------------------------------------------------------
# pyarmor subcommand — DEFERRED TO v2
# ---------------------------------------------------------------------------
# The pyarmor detect / unpack commands were removed in the v1 scope cut
# (see 05_ADVERSARIAL_REVIEW.md section 4.3). The supporting module is
# preserved as a v2 seed in pyglimmer_toolkit/core/pyarmor_unpacker.py.
# Reintroduce the commands when:
#   - Lil-House/Pyarmor-Static-Unpack-1shot v1.0.0 ships (expected 2027)
#   - DMCA §1201 lawyer review is complete
#   - User-supplied-binary safety is in place
# Tracked in v2 issues. Do not re-add to v1.


# ---------------------------------------------------------------------------
# pyarmor + dotnet subcommands — DEFERRED TO v2
# ---------------------------------------------------------------------------
# The `pyglimmer pyarmor detect/unpack` and `pyglimmer dotnet detect/deobfuscate`
# commands were removed in the v1 scope cut. See 05_ADVERSARIAL_REVIEW.md
# section 4.3 for the rationale.
#
# To re-enable in v2:
#   - pyarmor: when Lil-House/Pyarmor-Static-Unpack-1shot v1.0.0 ships
#     (expected 2027), after DMCA §1201 lawyer review, and with
#     user-supplied-binary safety in place.
#   - dotnet: build the C# .NET 8 sidecar (NDJSON-over-IPC, ICSharpCode.Decompiler
#     + AsmResolver). See 03_FEATURE_FEASIBILITY.md section ".NET Deobfuscation
#     Specialist Deep-Dive" for the full design.
#
# Tracked in v2 issues. Do not re-add to v1.


# ---------------------------------------------------------------------------
# python subcommand (v1 — the only shipped pillar)
# ---------------------------------------------------------------------------


@python_app.command("strip")
def python_strip(
    target: Annotated[Path, typer.Argument(exists=True)],
    out_dir: Annotated[Path, typer.Option("--out", "-o")] = Path("./out"),
    llm: Annotated[
        Optional[str],
        typer.Option(
            "--llm",
            help="LLM backend for cleanup pass: 'ollama:model', 'anthropic', 'openai', or omit to skip.",
        ),
    ] = None,
    send_to_cloud: Annotated[
        bool,
        typer.Option(
            "--send-to-cloud",
            help="Explicit opt-in to send decompiled source to a cloud LLM. Default OFF.",
        ),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Strip obfuscation layers from TARGET."""
    from pyglimmer_toolkit.core.generic_python_stripper import (
        GenericPythonStripper,
        StripperConfig,
    )

    config = StripperConfig(
        target=target,
        out_dir=out_dir,
        llm_backend=llm,
        send_to_cloud=send_to_cloud,
    )
    stripper = GenericPythonStripper(config)
    with console.status("[bold green]Stripping Python obfuscation...") as status:
        result = stripper.run_pipeline(
            on_progress=lambda p, m: status.update(f"{p:.0%} {m}")
        )

    if json_output:
        stdout_console.print_json(data=result.model_dump(mode="json"))
    else:
        console.print(result.summary_panel())

    if not result.success:
        raise typer.Exit(code=result.exit_code)


# ---------------------------------------------------------------------------
# pipeline subcommand
# ---------------------------------------------------------------------------


@pipeline_app.command("run")
def pipeline_run(
    target: Annotated[Path, typer.Argument(exists=True)],
    out_dir: Annotated[Path, typer.Option("--out", "-o")] = Path("./out"),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Auto-detect target type and run the applicable pillar(s)."""
    from pyglimmer_toolkit.core.pipeline import Pipeline

    pipeline = Pipeline(target=target, out_dir=out_dir)
    with console.status("[bold green]Running pipeline...") as status:
        result = pipeline.run(on_progress=lambda p, m: status.update(f"{p:.0%} {m}"))

    if json_output:
        stdout_console.print_json(data=result.model_dump(mode="json"))
    else:
        console.print(result.summary_panel())

    if not result.success:
        raise typer.Exit(code=result.exit_code)


def cli_entry() -> int:
    """Synchronous entry point used by both __main__.py and the script."""
    try:
        app()
        return 0
    except SystemExit as e:
        return int(e.code or 0)


if __name__ == "__main__":
    sys.exit(cli_entry())
