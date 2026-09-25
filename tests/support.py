"""Shared test helpers.

The entry point is an extensionless executable, so it is loaded by path rather
than imported by name.
"""

import importlib.machinery
import importlib.util
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")


def load_tool():
    path = os.path.join(ROOT, "network-doctor")
    loader = importlib.machinery.SourceFileLoader("network_doctor", path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


nd = load_tool()


def fixture(name):
    return os.path.join(FIXTURES, name)


def read_status(name):
    with open(fixture(name)) as handle:
        return json.load(handle)


def model_for(status_name, iperf_name=None):
    iperf = None
    if iperf_name is not None:
        iperf = nd.load_iperf(fixture(iperf_name))
        iperf["discovered"] = False
    return nd.build_model(read_status(status_name), status_name, iperf)


def verdicts_for(status_name, iperf_name=None):
    return nd.diagnose(model_for(status_name, iperf_name))


def kinds(verdicts):
    return [v["kind"] for v in verdicts]


def run_cli(argv, stdin_text=None):
    """Run main() capturing stdout, stderr and the exit status."""
    out, err = io.StringIO(), io.StringIO()
    old = (sys.stdout, sys.stderr, sys.stdin)
    sys.stdout, sys.stderr = out, err
    if stdin_text is not None:
        sys.stdin = io.StringIO(stdin_text)
    try:
        code = nd.main(argv)
    finally:
        sys.stdout, sys.stderr, sys.stdin = old
    return code, out.getvalue(), err.getvalue()


def units(model, space):
    return model["status"]["spaces"][space]["units"]
