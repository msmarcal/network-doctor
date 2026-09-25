"""Tests for the diagnosis capability."""

import unittest

from tests.support import nd, model_for, kinds, verdicts_for


def only(verdicts, kind):
    matching = [v for v in verdicts if v["kind"] == kind]
    assert matching, "no %s verdict in %s" % (kind, kinds(verdicts))
    return matching[0]


class EvidenceIsCarried(unittest.TestCase):
    def test_every_verdict_has_evidence_and_reasoning(self):
        for status, iperf in (("status_icmp_multi_peer.json", None),
                              ("status_space_wide_failure.json", None),
                              ("status_mtu_class_split.json", None),
                              ("status_cross_az.json", None),
                              ("status_healthy.json", "iperf_degraded_target.csv")):
            for verdict in verdicts_for(status, iperf):
                self.assertTrue(verdict["evidence"], verdict["title"])
                self.assertTrue(verdict["reasoning"], verdict["title"])

    def test_throughput_verdict_cites_values_per_space(self):
        verdict = only(verdicts_for("status_healthy.json",
                                    "iperf_degraded_target.csv"),
                       "throughput-host")
        self.assertEqual(verdict["hosts"], ["node-01"])
        for space in ("internal-space", "ceph-access-space", "public-space"):
            self.assertTrue(any(space in line and "18800" in line and "94200" in line
                                for line in verdict["evidence"]), space)

    def test_connectivity_verdict_names_hosts_spaces_and_counts(self):
        verdict = only(verdicts_for("status_space_wide_failure.json"), "space-wide")
        self.assertEqual(verdict["spaces"], ["internal-space"])
        joined = " ".join(verdict["evidence"])
        self.assertIn("node-04 -> node-01", joined)
        self.assertIn("0/20 packets", joined)


class HostAttribution(unittest.TestCase):
    def test_one_host_degraded_across_every_space(self):
        verdict = only(verdicts_for("status_healthy.json",
                                    "iperf_degraded_target.csv"),
                       "throughput-host")
        self.assertEqual(verdict["hosts"], ["node-01"])
        self.assertEqual(len(verdict["spaces"]), 3)

    def test_host_connectivity_needs_at_least_two_minority_spaces(self):
        # A single space failure is reported, but not as a multi-space host fault.
        self.assertNotIn("host-connectivity", kinds(verdicts_for("status_asymmetric.json")))


class SpaceAttribution(unittest.TestCase):
    def test_space_failing_on_all_hosts(self):
        verdicts = verdicts_for("status_space_wide_failure.json")
        verdict = only(verdicts, "space-wide")
        self.assertEqual(verdict["spaces"], ["internal-space"])
        self.assertEqual(len(verdict["hosts"]), 4)

    def test_space_verdict_does_not_blame_an_individual_host(self):
        verdicts = verdicts_for("status_space_wide_failure.json")
        self.assertNotIn("host-connectivity", kinds(verdicts))

    def test_healthy_space_is_untouched(self):
        verdict = only(verdicts_for("status_space_wide_failure.json"), "space-wide")
        self.assertNotIn("oam-space", verdict["spaces"])


class MtuCorrelation(unittest.TestCase):
    def test_failures_confined_to_9000(self):
        verdict = only(verdicts_for("status_mtu_class_split.json"), "mtu-class")
        self.assertIn("9000", verdict["title"])
        self.assertEqual(sorted(verdict["spaces"]),
                         ["ceph-access-space", "ceph-replica-space"])

    def test_both_sides_of_the_split_are_named(self):
        verdict = only(verdicts_for("status_mtu_class_split.json"), "mtu-class")
        joined = " ".join(verdict["evidence"])
        self.assertIn("ceph-access-space", joined)
        self.assertIn("oam-space", joined)
        self.assertIn("1500", joined)

    def test_no_correlation_when_mtu_classes_overlap(self):
        self.assertNotIn("mtu-class", kinds(verdicts_for("status_space_wide_failure.json")))


class ZoneCorrelation(unittest.TestCase):
    def test_failures_only_between_zones(self):
        verdict = only(verdicts_for("status_cross_az.json"), "cross-zone")
        self.assertIn("z1", " ".join(verdict["evidence"]))
        self.assertIn("z2", " ".join(verdict["evidence"]))

    def test_single_host_towards_another_zone_is_not_a_zone_fault(self):
        # One host failing outward looks like a zone pattern by coincidence.
        self.assertNotIn("cross-zone", kinds(verdicts_for("status_asymmetric.json")))

    def test_no_zone_verdict_when_zones_are_unknown(self):
        model = model_for("status_cross_az.json")
        for machine in model["status"]["machines"].values():
            machine["zone"] = None
        for space in model["status"]["spaces"].values():
            for unit in space["units"].values():
                unit["zone"] = None
                for peer in unit["icmp_peers"]:
                    peer["zone"] = None
        self.assertNotIn("cross-zone", kinds(nd.diagnose(model)))


class Asymmetry(unittest.TestCase):
    def test_one_way_failure_is_named(self):
        verdict = only(verdicts_for("status_asymmetric.json"), "one-way")
        self.assertIn("node-04", verdict["title"])
        self.assertIn("node-01", verdict["title"])
        self.assertIn("reaches it", " ".join(verdict["evidence"]))

    def test_direction_unknown_when_the_reverse_was_not_measured(self):
        model = model_for("status_asymmetric.json")
        target = model["status"]["spaces"]["internal-space"]["units"]["1"]
        target["checks"]["icmp"] = nd.ABSENT
        verdicts = nd.diagnose(model)
        verdict = only(verdicts, "direction-unknown")
        self.assertIn("reverse direction is unknown", " ".join(verdict["evidence"]))
        self.assertNotIn("one-way", kinds(verdicts))

    def test_mutual_failure_is_not_called_one_way(self):
        self.assertNotIn("one-way", kinds(verdicts_for("status_space_wide_failure.json")))


class ThroughputRules(unittest.TestCase):
    def test_comparison_stays_within_a_space(self):
        # Two spaces on a 1G NIC next to one on a 100G bond raise nothing.
        verdicts = verdicts_for("status_healthy.json", "iperf_slow_link_class.csv")
        self.assertEqual(verdicts, [])

    def test_common_path_verified_attributes_to_the_target(self):
        verdict = only(verdicts_for("status_healthy.json",
                                    "iperf_degraded_target.csv"),
                       "throughput-host")
        self.assertIn("common path is healthy", verdict["reasoning"])
        self.assertEqual(verdict["hosts"], ["node-01"])

    def test_scattered_peers_downgrade_to_an_observation(self):
        verdicts = verdicts_for("status_healthy.json", "iperf_all_degraded.csv")
        verdict = only(verdicts, "throughput-observation")
        self.assertNotIn("throughput-host", kinds(verdicts))
        self.assertIn("No target host is named", verdict["reasoning"])

    def test_common_path_helper(self):
        verified, _ = nd._common_path_verified([94200.0, 94200.0], 94200.0)
        self.assertTrue(verified)
        verified, reason = nd._common_path_verified([94200.0], 94200.0)
        self.assertFalse(verified)
        self.assertIn("too few", reason)
        verified, reason = nd._common_path_verified([12000.0, 6000.0], 9000.0)
        self.assertFalse(verified)
        self.assertIn("too few", reason)
        # Enough peers, but spread too wide to call the source path healthy.
        verified, reason = nd._common_path_verified(
            [12000.0, 8500.0, 8000.0], 8500.0)
        self.assertFalse(verified)
        self.assertIn("scattered", reason)


class Ranking(unittest.TestCase):
    def test_wider_blast_radius_comes_first(self):
        verdicts = verdicts_for("status_healthy.json", "iperf_degraded_target.csv")
        # Three spaces on one host outranks anything narrower.
        self.assertEqual(verdicts[0]["kind"], "throughput-host")

    def test_unsupported_charm_outranks_everything(self):
        verdicts = verdicts_for("status_ops_charm.json")
        self.assertEqual(verdicts[0]["tier"], 0)

    def test_ordering_is_deterministic(self):
        first = [v["title"] for v in verdicts_for("status_mtu_class_split.json")]
        second = [v["title"] for v in verdicts_for("status_mtu_class_split.json")]
        self.assertEqual(first, second)


class NoFindings(unittest.TestCase):
    def test_healthy_model_with_full_coverage(self):
        model = model_for("status_healthy.json")
        self.assertEqual(nd.diagnose(model), [])
        self.assertEqual(model["coverage"]["icmp"], "complete")

    def test_healthy_model_with_no_coverage(self):
        model = model_for("status_icmp_skipped.json")
        self.assertEqual(nd.diagnose(model), [])
        self.assertEqual(model["coverage"]["icmp"], "none")


class LocalChecks(unittest.TestCase):
    def test_bond_failure(self):
        verdict = only(verdicts_for("status_bonds_failed.json"), "local-bonds")
        self.assertEqual(verdict["hosts"], ["node-04"])
        self.assertIn("ens1f0 down", " ".join(verdict["evidence"]))

    def test_local_mtu_failure_cites_both_values(self):
        verdict = only(verdicts_for("status_mtu_failed.json"), "local-mtu")
        self.assertIn("required 9000", " ".join(verdict["evidence"]))
        self.assertIn("interface 1500", " ".join(verdict["evidence"]))


class DnsRules(unittest.TestCase):
    def test_dns_failure_with_clean_icmp_is_a_name_resolution_fault(self):
        verdict = only(verdicts_for("status_dns_variants.json"), "dns-only")
        self.assertIn("name resolution", verdict["reasoning"])

    def test_dns_failure_alongside_icmp_is_still_reported(self):
        verdicts = verdicts_for("status_icmp_multi_peer.json")
        verdict = only(verdicts, "dns-with-icmp")
        self.assertIn("may simply", verdict["reasoning"])

    def test_dns_peers_resolve_to_hostnames(self):
        verdict = only(verdicts_for("status_dns_variants.json"), "dns-only")
        self.assertTrue(any("node-" in line for line in verdict["evidence"]))


if __name__ == "__main__":
    unittest.main()
