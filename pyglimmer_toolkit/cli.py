"""Top-level CLI for pyglimmer-stripper.

Built on Typer + Rich. Four user-facing commands, plus a top-level
``--version`` callback:

    sigil version          Print version and exit.
    sigil detect TARGET    Sniff a target and report what protections
                           are present (file kind, magic bytes, layer
                           signatures).  No source is recovered.
    sigil strip TARGET     Run EXTRACT -> UNWRAP -> DECOMPILE -> LLM_CLEANUP
                           on TARGET and write the cleaned source to
                           --out.  Suitable for a single file.
    sigil pipeline TARGET  Auto-detect target kind and run the
                           appropriate pillar.  Alias of ``strip``
                           but documented separately for forward
                           compatibility (v2 will add .NET + PyArmor
                           pillars to ``pipeline``).
    sigil self-test        Run the obfuscated test bench and emit a
                           JSON report.  Used by CI and by humans to
                           verify the install.

The previous ``pyglimmer pyarmor`` and ``pyglimmer dotnet`` subcommands
were dropped in the v1 cut-scope; see ``05_ADVERSARIAL_REVIEW.md``
section 4.3 for the rationale.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pyglimmer_toolkit import __version__

app = typer.Typer(
    name="sigil",
    help="sigil: generic Python obfuscation stripper with optional LLM cleanup. v1 ships one pillar; .NET and PyArmor support deferred to v2.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
)

console = Console(stderr=True)
stdout_console = Console(file=sys.stdout)


def _version_callback(value: bool) -> None:
    """Print version and exit when --version is passed."""
    if value:
        stdout_console.print(f"pyglimmer-stripper {__version__}")
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
    """pyglimmer-stripper: see subcommands below."""


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------

@app.command("version")
def version_cmd() -> None:
    """Print version and exit."""
    stdout_console.print(f"pyglimmer-stripper {__version__}")
    raise typer.Exit(code=0)


# ---------------------------------------------------------------------------
# detect
# ---------------------------------------------------------------------------

@app.command("detect")
def detect_cmd(
    target: Annotated[Path, typer.Argument(exists=True, help="File to sniff.")],
) -> None:
    """Sniff TARGET and report what protections are present.

    Reads the first 4KB of the file and matches against known magic
    bytes and obfuscation-layer signatures.  Does NOT recover source.
    Use ``sigil strip`` for that.
    """
    from pyglimmer_toolkit.core.extract import sniff, PYINSTALLER_MAGIC, PYC_MAGIC_TABLE

    kind = sniff(target)
    head = target.open("rb").read(64)
    magic_hex = head[:4].hex() if len(head) >= 4 else "(file too small)"

    table = Table(title=f"Detection report: {target.name}", show_header=True,
                  header_style="bold cyan")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("path", str(target.resolve()))
    table.add_row("size_bytes", str(target.stat().st_size))
    table.add_row("magic_bytes", magic_hex)
    table.add_row("detected_kind", kind)
    if kind == "pyc":
        version_guess = "(unknown)"
        for mag, ver in PYC_MAGIC_TABLE.items():
            if mag == head[:4]:
                version_guess = ver[0] if isinstance(ver, tuple) else str(ver)
                break
        table.add_row("python_version_hint", version_guess)
    if kind == "pyinstaller":
        idx = head.find(PYINSTALLER_MAGIC)
        table.add_row("pyinstaller_cookie_offset", str(idx))
    console.print(table)


# ---------------------------------------------------------------------------
# strip
# ---------------------------------------------------------------------------

@app.command("strip")
def strip_cmd(
    target: Annotated[Path, typer.Argument(exists=True, help="File to strip.")],
    out_dir: Annotated[
        Path, typer.Option("--out", "-o", help="Output directory.")
    ] = Path("./out"),
    decompiler: Annotated[
        Optional[Path],
        typer.Option(
            "--decompiler",
            help="Path to the pycdc binary, or a directory containing it.  "
                 "If not provided, falls back to the in-process dis-fallback "
                 "(dev only) which produces structural source for trivial "
                 "bytecode only.",
        ),
    ] = None,
    llm: Annotated[
        Optional[str],
        typer.Option(
            "--llm",
            help="LLM backend for cleanup pass: 'ollama:model', "
                 "'anthropic:model', 'openai:model', 'passthrough', or omit to skip.",
        ),
    ] = None,
    send_to_cloud: Annotated[
        bool,
        typer.Option(
            "--send-to-cloud",
            help="Explicit opt-in to send decompiled source to a cloud LLM "
                 "(Anthropic, OpenAI).  Default OFF.  Ollama (local) does not "
                 "require this flag.",
        ),
    ] = False,
    timeout: Annotated[
        int,
        typer.Option("--timeout", help="Per-stage timeout in seconds."),
    ] = 120,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Strip obfuscation layers from TARGET and write the recovered source."""
    from pyglimmer_toolkit.core.generic_python_stripper import (
        GenericPythonStripper, StripperConfig,
    )

    config = StripperConfig(
        target=target,
        out_dir=out_dir,
        decompiler_path=decompiler,
        llm_backend=llm,
        send_to_cloud=send_to_cloud,
        timeout_seconds=timeout,
    )
    stripper = GenericPythonStripper(config)
    with console.status("[bold green]Stripping obfuscation...") as status:
        result = stripper.run_pipeline(
            on_progress=lambda p, m: status.update(f"{p:.0%} {m}")
        )

    if json_output:
        stdout_console.print_json(data=result.model_dump(mode="json"))
    else:
        console.print(result.summary_panel())

    if not result.success:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------

@app.command("pipeline")
def pipeline_cmd(
    target: Annotated[Path, typer.Argument(exists=True, help="File to process.")],
    out_dir: Annotated[
        Path, typer.Option("--out", "-o", help="Output directory.")
    ] = Path("./out"),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Auto-detect TARGET kind and run the appropriate pillar.

    Currently equivalent to ``sigil strip`` (the only v1 pillar is the
    generic Python stripper).  Kept as a separate command so v2 can
    add .NET + PyArmor dispatch without breaking callers.
    """
    from pyglimmer_toolkit.core.pipeline import Pipeline

    pipeline = Pipeline(target=target, out_dir=out_dir)
    with console.status("[bold green]Running pipeline...") as status:
        result = pipeline.run(on_progress=lambda p, m: status.update(f"{p:.0%} {m}"))

    if json_output:
        stdout_console.print_json(data=result.model_dump(mode="json"))
    else:
        console.print(result.summary_panel())

    if not result.success:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------

@app.command("self-test")
def self_test_cmd(
    cases_dir: Annotated[
        Path, typer.Option("--cases", help="Eval cases directory.")
    ] = Path("eval/cases"),
    out: Annotated[
        Path, typer.Option("--out", help="Where to write report.json.")
    ] = Path("eval/report.json"),
    decompiler: Annotated[
        Optional[Path],
        typer.Option("--decompiler", help="Path to pycdc binary."),
    ] = None,
    with_cleanup: Annotated[
        bool,
        typer.Option("--with-cleanup", help="Enable LLM cleanup pass."),
    ] = False,
) -> None:
    """Run the obfuscated test bench and write a JSON report.

    Grades Sigil against every case in ``--cases`` for every layer set
    (L1 base64, L2 marshal, L3 zlib+marshal, L5 lambda wall, L6 .pyc).
    Each case x layer is run 5 times with seeded random inputs; output
    is compared to the un-obfuscated case's main() return value.
    """
    import os
    here = Path(__file__).parent.parent  # project root (one above the package)
    cwd_was = os.getcwd()
    try:
        os.chdir(here)
        from eval import run_eval
        rc = run_eval.main([
            "--cases-dir", str(cases_dir),
            "--out", str(out),
            "--seed", "42",
        ] + (["--with-cleanup"] if with_cleanup else [])
          + (["--decompiler-path", str(decompiler)] if decompiler else []))
    finally:
        os.chdir(cwd_was)

    if out.exists():
        report = json.loads(out.read_text(encoding="utf-8"))
        totals = report.get("totals", {})
        matches = totals.get("matches", 0)
        grand = totals.get("total", 0)
        pct = totals.get("percent", 0.0)
        panel = Panel(
            f"[bold]{matches} / {grand} = {pct:.1f}%[/bold]\n"
            f"Report: {out}",
            title="Self-test complete",
            border_style="green" if pct >= 80.0 else "yellow" if pct >= 40.0 else "red",
        )
        console.print(panel)
    else:
        console.print(f"[red]self-test failed; report not written to {out}[/red]")

    raise typer.Exit(code=rc)


def cli_entry() -> int:
    """Synchronous entry point used by both __main__.py and the script."""
    try:
        app()
        return 0
    except SystemExit as e:
        return int(e.code or 0)


if __name__ == "__main__":
    sys.exit(cli_entry())
