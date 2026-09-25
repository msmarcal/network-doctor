"""Tests for the status-parsing capability."""

import unittest

from tests.support import nd, model_for, read_status, units

OK, FAILED, ABSENT = nd.OK, nd.FAILED, nd.ABSENT

FULL = ("ports ok, bonds ok, icmp ok, local hostname ok (node-01), dns ok, "
        "local mtu ok, required:             1500")


class SixFieldGrammar(unittest.TestCase):
    def test_full_message_yields_every_field(self):
        parsed = nd.parse_message(FULL)
        self.assertEqual(parsed["form"], "checks")
        for name in nd.CHECKS:
            self.assertEqual(parsed["checks"][name], OK, name)
        self.assertEqual(parsed["reported_hostname"], "node-01")
        self.assertEqual(parsed["required_mtu"], 1500)
        self.assertEqual(parsed["unrecognized"], "")

    def test_bracketed_dns_list_is_not_split_on_its_comma(self):
        message = ("bonds ok, icmp ok, local hostname ok (node-03), "
                   "rev dns failed: ['1', '2'], local mtu ok, "
                   "required:             9000")
        parsed = nd.parse_message(message)
        self.assertEqual(parsed["checks"]["dns"], FAILED)
        self.assertEqual([p["unit_id"] for p in parsed["dns_peers"]], ["1", "2"])
        self.assertEqual(parsed["required_mtu"], 9000)
        self.assertEqual(parsed["unrecognized"], "")

    def test_unrecognized_field_does_not_block_the_others(self):
        parsed = nd.parse_message(
            "bonds ok, icmp ok, local hostname ok (node-01), dns ok, "
            "local mtu ok, required:             1500, something new here")
        self.assertEqual(parsed["checks"]["icmp"], OK)
        self.assertEqual(parsed["required_mtu"], 1500)
        self.assertIn("something new here", parsed["unrecognized"])

    def test_every_dns_failure_kind_is_recognized(self):
        for kind in ("rev", "fwd", "match"):
            parsed = nd.parse_message(
                "icmp ok, %s dns failed: ['2']" % kind)
            self.assertEqual(parsed["checks"]["dns"], FAILED)
            self.assertEqual(parsed["dns_peers"][0]["kind"], kind)

    def test_port_and_bond_failure_detail_is_kept(self):
        parsed = nd.parse_message(
            "ports failed: eth0:wrong, bonds failed: bond0:slave down, icmp ok")
        self.assertEqual(parsed["checks"]["ports"], FAILED)
        self.assertEqual(parsed["detail"]["ports"], "eth0:wrong")
        self.assertEqual(parsed["checks"]["bonds"], FAILED)
        self.assertEqual(parsed["detail"]["bonds"], "bond0:slave down")


class PeerResolution(unittest.TestCase):
    def test_unit_numbering_differs_from_machine_numbering(self):
        model = model_for("status_permutation.json")
        space = units(model, "internal-space")
        # The fixture places unit 1 on machine 0, whose hostname is node-01.
        self.assertEqual(space["1"]["machine"], "0")
        self.assertEqual(space["1"]["hostname"], "node-01")
        peers = space["1"]["icmp_peers"]
        self.assertEqual(len(peers), 1)
        self.assertEqual(peers[0]["unit_id"], "0")
        self.assertEqual(peers[0]["machine"], "3")
        self.assertEqual(peers[0]["hostname"], "node-04")
        self.assertTrue(peers[0]["resolved"])

    def test_identity_assumption_would_be_wrong(self):
        model = model_for("status_permutation.json")
        space = units(model, "internal-space")
        mismatched = [u for u in space.values() if u["unit_id"] != u["machine"]]
        self.assertGreaterEqual(len(mismatched), 3)

    def test_unknown_identifier_is_marked_unresolved_and_run_continues(self):
        model = model_for("status_unresolved_peer.json")
        space = units(model, "internal-space")
        peers = {p["unit_id"]: p for p in space["0"]["icmp_peers"]}
        self.assertEqual(sorted(peers), ["1", "9"])
        self.assertTrue(peers["1"]["resolved"])
        self.assertFalse(peers["9"]["resolved"])
        self.assertIsNone(peers["9"]["hostname"])
        # Every other unit was still processed.
        self.assertEqual(len(space), 4)

    def test_unresolved_identifier_is_reported(self):
        verdicts = nd.diagnose(model_for("status_unresolved_peer.json"))
        unresolved = [v for v in verdicts if v["kind"] == "unresolved-peer"]
        self.assertEqual(len(unresolved), 1)
        self.assertTrue(any("unit 9" in line for line in unresolved[0]["evidence"]))


class CompletePeerEnumeration(unittest.TestCase):
    def test_all_peers_in_one_message_are_reported(self):
        parsed = nd.parse_message(
            "icmp failed: 1: 0/20 packets received; 2: 0/20 packets received")
        self.assertEqual(len(parsed["icmp_peers"]), 2)
        self.assertEqual([p["unit_id"] for p in parsed["icmp_peers"]], ["1", "2"])
        for peer in parsed["icmp_peers"]:
            self.assertEqual(peer["received"], 0)
            self.assertEqual(peer["transmitted"], 20)

    def test_many_peers(self):
        entries = "; ".join(
            "%d: 0/20 packets received" % i for i in range(1, 19))
        parsed = nd.parse_message("icmp failed: " + entries)
        self.assertEqual(len(parsed["icmp_peers"]), 18)

    def test_icmp_failure_without_a_following_field(self):
        parsed = nd.parse_message("icmp failed: 1: 0/20 packets received")
        self.assertEqual(parsed["checks"]["icmp"], FAILED)
        self.assertEqual(len(parsed["icmp_peers"]), 1)

    def test_partial_loss_counts_are_kept(self):
        parsed = nd.parse_message("icmp failed: 3: 17/20 packets received")
        peer = parsed["icmp_peers"][0]
        self.assertEqual((peer["received"], peer["transmitted"]), (17, 20))


class RequiredMtu(unittest.TestCase):
    def test_unknown_space_name_takes_the_mtu_from_the_message(self):
        parsed = nd.parse_message(
            "icmp ok, local mtu ok, required:             9000")
        self.assertEqual(parsed["required_mtu"], 9000)

    def test_absent_mtu_field_is_absent_not_a_default(self):
        parsed = nd.parse_message("icmp ok, dns ok")
        self.assertIsNone(parsed["required_mtu"])
        self.assertEqual(parsed["checks"]["mtu"], ABSENT)

    def test_mtu_failure_records_both_values(self):
        parsed = nd.parse_message(
            "icmp ok, local mtu failed,         required: 9000, iface: 1500")
        self.assertEqual(parsed["checks"]["mtu"], FAILED)
        self.assertEqual(parsed["required_mtu"], 9000)
        self.assertEqual(parsed["iface_mtu"], 1500)

    def test_space_required_mtu_comes_from_its_units(self):
        model = model_for("status_healthy.json")
        self.assertEqual(
            model["status"]["spaces"]["ceph-access-space"]["required_mtu"], 9000)
        self.assertEqual(
            model["status"]["spaces"]["oam-space"]["required_mtu"], 1500)


class TriState(unittest.TestCase):
    def test_skipped_is_distinguishable_from_ok(self):
        skipped = nd.parse_message("icmp skipped, dns ok")
        healthy = nd.parse_message("icmp ok, dns ok")
        self.assertEqual(skipped["checks"]["icmp"], ABSENT)
        self.assertEqual(healthy["checks"]["icmp"], OK)
        self.assertNotEqual(skipped["checks"]["icmp"], healthy["checks"]["icmp"])

    def test_missing_field_is_not_ok(self):
        parsed = nd.parse_message("icmp ok")
        self.assertEqual(parsed["checks"]["bonds"], ABSENT)
        self.assertNotEqual(parsed["checks"]["bonds"], OK)

    def test_every_check_is_one_of_three_values(self):
        parsed = nd.parse_message(FULL)
        for value in parsed["checks"].values():
            self.assertIn(value, (OK, FAILED, ABSENT))


class ParseAccounting(unittest.TestCase):
    def test_unknown_format_is_counted(self):
        model = model_for("status_unparsable.json")
        self.assertEqual(model["status"]["unparsed_messages"], 1)
        self.assertEqual(model["coverage"]["unparsed_messages"], 1)

    def test_clean_run_reports_zero_unparsed(self):
        model = model_for("status_healthy.json")
        self.assertEqual(model["coverage"]["unparsed_messages"], 0)

    def test_unparsed_message_is_not_discarded(self):
        model = model_for("status_unparsable.json")
        broken = units(model, "internal-space")["0"]
        self.assertEqual(broken["form"], "unparsed")
        self.assertIn("hook failed", broken["raw"])


class KnownNonCheckForms(unittest.TestCase):
    def test_leader_status_is_recognized(self):
        parsed = nd.parse_message("Concurrency: 8 Nodes: magpie-oam-space/1")
        self.assertEqual(parsed["form"], "leader-status")
        for value in parsed["checks"].values():
            self.assertEqual(value, ABSENT)

    def test_leader_status_does_not_count_as_unparsed(self):
        model = model_for("status_leader.json")
        self.assertEqual(model["coverage"]["unparsed_messages"], 0)
        leader = units(model, "internal-space")["0"]
        self.assertEqual(leader["role"], "leader")

    def test_ops_charm_form_is_detected(self):
        model = model_for("status_ops_charm.json")
        self.assertEqual(model["status"]["charm"], "ops")

    def test_ops_charm_is_reported_as_unsupported(self):
        verdicts = nd.diagnose(model_for("status_ops_charm.json"))
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0]["kind"], "unsupported-charm")
        self.assertEqual(verdicts[0]["tier"], 0)

    def test_reactive_charm_is_the_default(self):
        self.assertEqual(model_for("status_healthy.json")["status"]["charm"],
                         "reactive")


class MachineInventory(unittest.TestCase):
    def test_machine_without_availability_zone(self):
        model = model_for("status_no_az.json")
        machines = model["status"]["machines"]
        self.assertIsNone(machines["1"]["zone"])
        self.assertEqual(machines["1"]["hostname"], "node-02")

    def test_run_completes_and_reports_all_machines(self):
        model = model_for("status_no_az.json")
        self.assertEqual(len(model["status"]["machines"]), 4)
        self.assertEqual(model["coverage"]["machines"], 4)
        for machine_id in ("0", "2", "3"):
            self.assertIsNotNone(model["status"]["machines"][machine_id]["zone"])

    def test_zone_extraction(self):
        self.assertEqual(nd._zone("arch=amd64 availability-zone=AZ1"), "AZ1")
        self.assertIsNone(nd._zone("arch=amd64 cores=8"))
        self.assertIsNone(nd._zone(None))


class NormalizedModel(unittest.TestCase):
    def test_model_round_trips_through_json(self):
        import json as _json
        model = model_for("status_icmp_multi_peer.json")
        restored = _json.loads(_json.dumps(model["status"], sort_keys=True))
        self.assertEqual(restored, model["status"])

    def test_document_without_magpie_applications(self):
        document = read_status("status_healthy.json")
        document["applications"] = {
            "ubuntu": {"application-status": {"current": "active", "message": ""},
                       "units": {}}}
        model = nd.build_model(document, "synthetic", None)
        self.assertEqual(model["status"]["spaces"], {})
        self.assertEqual(model["coverage"]["icmp"], "none")


if __name__ == "__main__":
    unittest.main()
