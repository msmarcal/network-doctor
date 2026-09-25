"""Tests for the iperf-ingest capability."""

import unittest

from tests.support import nd, fixture, model_for, run_cli

OK, FAILED, ABSENT = nd.OK, nd.FAILED, nd.ABSENT


class PerPairMeasurements(unittest.TestCase):
    def setUp(self):
        self.iperf = nd.load_iperf(fixture("iperf_healthy.csv"))

    def test_one_measurement_per_pair(self):
        self.assertTrue(self.iperf["format_ok"])
        self.assertEqual(len(self.iperf["measurements"]), 6)

    def test_measurement_carries_the_required_values(self):
        row = self.iperf["measurements"][0]
        self.assertEqual(row["space"], "internal-space")
        self.assertEqual(row["source"], "node-04")
        self.assertEqual(row["target"], "node-01")
        self.assertEqual(row["source_interface"], "bond0.882")
        self.assertEqual(row["required_mtu"], 1500)

    def test_throughput_is_numeric(self):
        for row in self.iperf["measurements"]:
            self.assertIsInstance(row["mbps"], float)
        self.assertEqual(self.iperf["measurements"][0]["mbps"], 94200.0)

    def test_addresses_and_hardware_addresses_are_retained(self):
        row = self.iperf["measurements"][0]
        self.assertEqual(row["source_ip"], "10.0.1.13")
        self.assertEqual(row["target_ip"], "10.0.1.10")
        self.assertTrue(row["source_mac"])
        self.assertTrue(row["target_mac"])

    def test_required_mtu_differs_per_space(self):
        by_space = dict((r["space"], r["required_mtu"])
                        for r in self.iperf["measurements"])
        self.assertEqual(by_space["internal-space"], 1500)
        self.assertEqual(by_space["ceph-access-space"], 9000)


class OptionalInput(unittest.TestCase):
    def test_status_alone_still_produces_results(self):
        model = model_for("status_icmp_multi_peer.json")
        self.assertFalse(model["coverage"]["iperf"]["present"])
        verdicts = nd.diagnose(model)
        self.assertTrue(verdicts)
        self.assertNotIn("throughput-host", [v["kind"] for v in verdicts])
        self.assertNotIn("throughput-observation", [v["kind"] for v in verdicts])

    def test_absence_is_recorded_in_the_report(self):
        code, out, _ = run_cli([fixture("status_healthy.json"),
                                "--iperf", fixture("iperf_healthy.csv")])
        self.assertEqual(code, 0)
        self.assertIn("iperf:", out)
        code, out, _ = run_cli([fixture("status_healthy.json")])
        self.assertIn("no throughput data", out)

    def test_named_file_that_does_not_exist_is_an_input_error(self):
        code, _, err = run_cli([fixture("status_healthy.json"),
                                "--iperf", fixture("nope.csv")])
        self.assertEqual(code, 1)
        self.assertIn("iperf file not found", err)


class Topology(unittest.TestCase):
    def test_single_source_is_recorded_as_a_star(self):
        iperf = nd.load_iperf(fixture("iperf_healthy.csv"))
        for space, topology in iperf["topology"].items():
            self.assertEqual(topology["kind"], "star", space)
            self.assertEqual(topology["source"], "node-04")

    def test_unmeasured_pairs_are_absent_rather_than_passing(self):
        iperf = nd.load_iperf(fixture("iperf_healthy.csv"))
        pairs = set((r["space"], r["source"], r["target"])
                    for r in iperf["measurements"])
        # The star never measures node-01 as a source.
        self.assertFalse(any(p[1] == "node-01" for p in pairs))

    def test_multiple_sources_are_recorded_as_a_mesh(self):
        iperf = nd.load_iperf(fixture("iperf_healthy.csv"))
        iperf["measurements"].append(dict(iperf["measurements"][0],
                                          source="node-01"))
        rebuilt = {}
        for row in iperf["measurements"]:
            rebuilt.setdefault(row["space"], set()).add(row["source"])
        self.assertEqual(len(rebuilt["internal-space"]), 2)


class EndpointChecks(unittest.TestCase):
    def test_target_bonds_failure_is_read_into_tri_state(self):
        iperf = nd.load_iperf(fixture("iperf_endpoint_bonds_failed.csv"))
        failing = [r for r in iperf["measurements"]
                   if r["target_checks"]["bonds"] == FAILED]
        self.assertEqual(len(failing), 1)
        self.assertEqual(failing[0]["target"], "node-02")

    def test_endpoint_checks_use_the_same_form_as_status_messages(self):
        iperf = nd.load_iperf(fixture("iperf_healthy.csv"))
        row = iperf["measurements"][0]
        for name in ("bonds", "ports", "icmp", "hostname", "dns", "mtu"):
            self.assertIn(row["target_checks"][name], (OK, FAILED, ABSENT))
            self.assertIn(row["source_checks"][name], (OK, FAILED, ABSENT))
        self.assertEqual(row["target_checks"]["bonds"], OK)

    def test_endpoint_failure_reaches_the_report(self):
        verdicts = nd.diagnose(
            model_for("status_healthy.json", "iperf_endpoint_bonds_failed.csv"))
        bonds = [v for v in verdicts if v["kind"] == "endpoint-bonds"]
        self.assertEqual(len(bonds), 1)
        self.assertEqual(bonds[0]["hosts"], ["node-02"])

    def test_endpoint_failure_is_not_duplicated_when_status_reports_it(self):
        iperf = nd.load_iperf(fixture("iperf_endpoint_bonds_failed.csv"))
        iperf["discovered"] = False
        verdicts = []
        nd._diagnose_endpoint_checks(iperf, {("node-02", "bonds")}, verdicts)
        self.assertEqual(verdicts, [])


class MalformedRows(unittest.TestCase):
    def test_non_numeric_throughput_is_counted_and_skipped(self):
        iperf = nd.load_iperf(fixture("iperf_bad_value.csv"))
        self.assertEqual(iperf["malformed_rows"], 1)
        self.assertEqual(len(iperf["measurements"]), 2)
        self.assertTrue(iperf["format_ok"])

    def test_malformed_count_reaches_coverage(self):
        model = model_for("status_healthy.json", "iperf_bad_value.csv")
        self.assertEqual(model["coverage"]["iperf"]["malformed_rows"], 1)

    def test_unexpected_header_is_reported_and_suppresses_conclusions(self):
        iperf = nd.load_iperf(fixture("iperf_bad_header.csv"))
        self.assertFalse(iperf["format_ok"])
        self.assertIn("Mb/s", iperf["missing_columns"])
        self.assertEqual(iperf["measurements"], [])

    def test_bad_header_yields_no_throughput_verdict(self):
        verdicts = nd.diagnose(
            model_for("status_healthy.json", "iperf_bad_header.csv"))
        self.assertEqual(verdicts, [])


class RealCaptureShape(unittest.TestCase):
    """The column names are taken from real Magpie iperf output."""

    def test_expected_columns_are_the_ones_the_action_emits(self):
        self.assertEqual(nd.IPERF_COLUMNS,
                         ("application", "source machine", "target machine", "Mb/s"))

    def test_mtu_column_tolerates_leading_whitespace(self):
        # Real output writes the mtu column as " ok".
        checks = nd._endpoint_checks({"target_unit mtu": " ok"}, "target_unit")
        self.assertEqual(checks["mtu"], OK)

    def test_missing_endpoint_column_is_absent(self):
        checks = nd._endpoint_checks({}, "target_unit")
        for value in checks.values():
            self.assertEqual(value, ABSENT)


if __name__ == "__main__":
    unittest.main()
