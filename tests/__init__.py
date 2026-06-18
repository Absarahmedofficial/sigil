"""pyglimmer_toolkit pytest test suite.

This package contains unit and integration tests for the four
pipeline stages (extract, unwrap, decompile, llm_cleanup) and for
the CLI surface.

Run with:
    pytest tests/

Files:
    conftest.py            Shared fixtures (small .py, .pyc, marshal,
                           zlib+marshal, lambda wall, PyInstaller,
                           random binary)
    test_detect.py         sniff() classification
    test_unwrap.py         unwrap_once / unwrap_iter / marker roundtrip
    test_decompile.py      decompile_file routing + dis-fallback
    test_pipeline.py       Pipeline.detect / Pipeline.run + pydantic models
    test_cleanup.py        ast signature + semantic diff + llm_cleanup_file
    test_cli.py            subprocess tests for the 5 CLI commands
"""
