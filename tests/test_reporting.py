"""Tests for the reporting capability."""

import json
import os
import re
import shutil
import tempfile
import unittest

from tests.support import ROOT, nd, fixture, run_cli

ANSI = re.compile(r"\033\[")


class VerdictFirstLayout(unittest.TestCase):
    def test_verdicts_precede_supporting_detail(self):
        code, out, _ = run_cli([fixture("status_unresolved_peer.json")])
        self.assertEqual(code, 2)
        first = out.index("[1]")
        self.assertLess(first, out.index("UNRECOGNIZED")
                        if "UNRECOGNIZED" in out else len(out))

    def test_verdicts_are_numbered_in_rank_order(self):
        code, out, _ = run_cli([fixture("status_healthy.json"),
                                "--iperf", fixture("iperf_degraded_target.csv")])
        self.assertEqual(code, 2)
        self.assertIn("[1] Host node-01 is far below its peers in 3 spaces", out)

    def test_evidence_and_reading_appear_under_each_verdict(self):
        _, out, _ = run_cli([fixture("status_bonds_failed.json")])
        self.assertIn("evidence", out)
        self.assertIn("reading", out)


class CoverageHeader(unittest.TestCase):
    def test_names_both_inputs_and_counts(self):
        _, out, _ = run_cli([fixture("status_healthy.json"),
                             "--iperf", fixture("iperf_healthy.csv")])
        self.assertIn("status: ", out)
        self.assertIn("iperf: ", out)
        self.assertIn("4 machines, 2 spaces", out)
        self.assertIn("icmp: measured on every unit", out)
        self.assertIn("0 unparsed messages", out)
        self.assertIn("0 malformed rows", out)
        self.assertIn("star from node-04", out)

    def test_leader_only_icmp_is_stated(self):
        with open(fixture("status_icmp_skipped.json")) as handle:
            document = json.load(handle)
        space = document["applications"]["magpie-internal-space"]["units"]
        key = sorted(space)[0]
        space[key]["workload-status"]["message"] = space[key][
            "workload-status"]["message"].replace("icmp skipped", "icmp ok")
        model = nd.build_model(document, "synthetic", None)
        self.assertEqual(model["coverage"]["icmp"], "leader-only")
        text = nd.render_text(model, nd.diagnose(model), nd.Painter(False))
        self.assertIn("measured from the leader only", text)

    def test_no_icmp_coverage_is_stated(self):
        _, out, _ = run_cli([fixture("status_icmp_skipped.json")])
        self.assertIn("not measured on any unit", out)
        self.assertIn("says nothing about", out)

    def test_unparsed_messages_are_counted_in_the_header(self):
        _, out, _ = run_cli([fixture("status_unparsable.json")])
        self.assertIn("1 unparsed message", out)

    def test_pluralization(self):
        self.assertEqual(nd._plural(1, "machine"), "1 machine")
        self.assertEqual(nd._plural(2, "machine"), "2 machines")


class JsonOutput(unittest.TestCase):
    def setUp(self):
        code, out, _ = run_cli([fixture("status_healthy.json"),
                                "--iperf", fixture("iperf_degraded_target.csv"),
                                "--json"])
        self.code, self.raw = code, out
        self.payload = json.loads(out)

    def test_output_parses_as_json(self):
        self.assertIsInstance(self.payload, dict)

    def test_contains_model_coverage_measurements_and_verdicts(self):
        for key in ("coverage", "model", "measurements", "verdicts"):
            self.assertIn(key, self.payload)
        self.assertIn("machines", self.payload["model"])
        self.assertIn("spaces", self.payload["model"])
        self.assertTrue(self.payload["measurements"])
        self.assertTrue(self.payload["verdicts"])

    def test_contains_no_ansi(self):
        self.assertIsNone(ANSI.search(self.raw))

    def test_exit_status_still_reflects_findings(self):
        self.assertEqual(self.code, 2)

    def test_check_results_are_present_per_unit(self):
        spaces = self.payload["model"]["spaces"]
        unit = list(spaces["oam-space"]["units"].values())[0]
        for name in nd.CHECKS:
            self.assertIn(name, unit["checks"])


class ColorGating(unittest.TestCase):
    def test_redirected_output_has_no_ansi(self):
        _, out, _ = run_cli([fixture("status_bonds_failed.json")])
        self.assertIsNone(ANSI.search(out))

    def test_no_color_flag_suppresses_ansi(self):
        _, out, _ = run_cli([fixture("status_bonds_failed.json"), "--no-color"])
        self.assertIsNone(ANSI.search(out))

    def test_painter_emits_color_only_when_enabled(self):
        self.assertEqual(nd.Painter(False)("x", nd.RED), "x")
        self.assertIn("\033[", nd.Painter(True)("x", nd.RED))


class AsciiOnly(unittest.TestCase):
    def test_every_fixture_renders_as_ascii(self):
        statuses = [f for f in os.listdir(os.path.join(ROOT, "tests", "fixtures"))
                    if f.startswith("status_") and f.endswith(".json")]
        self.assertTrue(statuses)
        for name in statuses:
            _, out, _ = run_cli([fixture(name)])
            try:
                out.encode("ascii")
            except UnicodeEncodeError as exc:
                self.fail("%s produced non-ASCII output: %s" % (name, exc))

    def test_report_with_iperf_is_ascii(self):
        _, out, _ = run_cli([fixture("status_healthy.json"),
                             "--iperf", fixture("iperf_degraded_target.csv")])
        out.encode("ascii")

    def test_source_file_is_ascii(self):
        with open(os.path.join(ROOT, "network-doctor"), "rb") as handle:
            handle.read().decode("ascii")


class EmptySections(unittest.TestCase):
    def test_no_unrecognized_heading_when_everything_parsed(self):
        _, out, _ = run_cli([fixture("status_healthy.json")])
        self.assertNotIn("UNRECOGNIZED", out)

    def test_heading_appears_only_with_content(self):
        _, out, _ = run_cli([fixture("status_unparsable.json")])
        self.assertIn("UNRECOGNIZED", out)
        index = out.index("UNRECOGNIZED")
        self.assertTrue(out[index:].strip().count("\n") >= 1)

    def test_no_dns_section_when_dns_is_clean(self):
        _, out, _ = run_cli([fixture("status_healthy.json")])
        self.assertNotIn("DNS resolution failing", out)


class InputHandling(unittest.TestCase):
    def test_status_on_standard_input(self):
        with open(fixture("status_bonds_failed.json")) as handle:
            text = handle.read()
        code, out, _ = run_cli([], stdin_text=text)
        self.assertEqual(code, 2)
        self.assertIn("Bond check failed", out)
        self.assertIn("<stdin>", out)

    def test_sibling_iperf_is_discovered(self):
        workdir = tempfile.mkdtemp()
        try:
            shutil.copy(fixture("status_healthy.json"),
                        os.path.join(workdir, "juju-status.json"))
            shutil.copy(fixture("iperf_degraded_target.csv"),
                        os.path.join(workdir, "iperf.csv"))
            code, out, _ = run_cli([os.path.join(workdir, "juju-status.json")])
            self.assertEqual(code, 2)
            self.assertIn("found beside the status file", out)
            self.assertIn("iperf.csv", out)
        finally:
            shutil.rmtree(workdir)

    def test_no_sibling_means_no_iperf(self):
        workdir = tempfile.mkdtemp()
        try:
            shutil.copy(fixture("status_healthy.json"),
                        os.path.join(workdir, "juju-status.json"))
            code, out, _ = run_cli([os.path.join(workdir, "juju-status.json")])
            self.assertEqual(code, 0)
            self.assertIn("not supplied", out)
        finally:
            shutil.rmtree(workdir)


class ExitStatus(unittest.TestCase):
    def test_clean_run_exits_zero(self):
        code, _, _ = run_cli([fixture("status_healthy.json")])
        self.assertEqual(code, 0)

    def test_findings_exit_two(self):
        code, _, _ = run_cli([fixture("status_bonds_failed.json")])
        self.assertEqual(code, 2)

    def test_missing_file_exits_one_with_a_reason(self):
        code, _, err = run_cli([fixture("does_not_exist.json")])
        self.assertEqual(code, 1)
        self.assertIn("status file not found", err)

    def test_invalid_json_exits_one_with_a_reason(self):
        workdir = tempfile.mkdtemp()
        try:
            path = os.path.join(workdir, "broken.json")
            with open(path, "w") as handle:
                handle.write("{not json")
            code, _, err = run_cli([path])
            self.assertEqual(code, 1)
            self.assertIn("not valid JSON", err)
        finally:
            shutil.rmtree(workdir)

    def test_json_that_is_not_juju_status_exits_one(self):
        workdir = tempfile.mkdtemp()
        try:
            path = os.path.join(workdir, "other.json")
            with open(path, "w") as handle:
                handle.write('{"hello": "world"}')
            code, _, err = run_cli([path])
            self.assertEqual(code, 1)
            self.assertIn("does not look like juju status", err)
        finally:
            shutil.rmtree(workdir)


if __name__ == "__main__":
    unittest.main()
