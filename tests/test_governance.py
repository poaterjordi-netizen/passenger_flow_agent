import json
import tempfile
import unittest
from pathlib import Path

from metro_agent.governance import PromotionGateEvaluation, assistant_availability


ROOT = Path(__file__).resolve().parents[1]


class PromotionGovernanceTests(unittest.TestCase):
    def test_repository_gate_is_machine_readable_and_fail_closed(self) -> None:
        gate = PromotionGateEvaluation.load(ROOT / "config" / "production_promotion_gates.json")

        self.assertFalse(gate.ready)
        self.assertEqual(gate.configured_status, "blocked_pending_approval")
        self.assertIn("owners_incomplete", gate.blockers)
        self.assertIn("thresholds_incomplete", gate.blockers)
        self.assertIn("required_artifacts_incomplete", gate.blockers)
        self.assertIn("business_owner", gate.missing_owner_roles)
        self.assertIn("business_correctness_min", gate.missing_thresholds)
        self.assertIn("uat_signoff", gate.pending_artifacts)

    def test_approved_gate_requires_owners_thresholds_and_artifact_refs(self) -> None:
        payload = json.loads(
            (ROOT / "config" / "production_promotion_gates.json").read_text(encoding="utf-8")
        )
        payload["status"] = "approved"
        payload["owners"] = {name: f"decision:{name}" for name in payload["owners"]}
        for name, value in payload["thresholds"].items():
            if value is None:
                payload["thresholds"][name] = 0.95 if name.endswith("_min") else 10
        payload["required_artifacts"] = {
            name: {"status": "approved", "approval_ref": f"artifact:{name}"}
            for name in payload["required_artifacts"]
        }

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "gate.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            gate = PromotionGateEvaluation.load(path)

        self.assertTrue(gate.ready)
        self.assertEqual(gate.blockers, ())
        enabled, status = assistant_availability(
            data_scope="production-shadow",
            runtime_flag_requested=True,
            promotion_gate=gate,
        )
        self.assertTrue(enabled)
        self.assertEqual(status, "enabled_after_promotion")

    def test_invalid_gate_blocks_production_assistant(self) -> None:
        gate = PromotionGateEvaluation.load(Path("/path/that/does/not/exist.json"))
        enabled, status = assistant_availability(
            data_scope="production-shadow",
            runtime_flag_requested=True,
            promotion_gate=gate,
        )

        self.assertFalse(enabled)
        self.assertEqual(status, "blocked_by_promotion_gate")
        self.assertEqual(gate.blockers, ("promotion_gate_configuration_invalid",))

    def test_runtime_flag_is_an_independent_production_gate(self) -> None:
        gate = PromotionGateEvaluation.load(ROOT / "config" / "production_promotion_gates.json")
        enabled, status = assistant_availability(
            data_scope="production-shadow",
            runtime_flag_requested=False,
            promotion_gate=gate,
        )

        self.assertFalse(enabled)
        self.assertEqual(status, "disabled_by_runtime_flag")

    def test_explicit_local_live_shadow_acknowledgement_is_visible_not_promoted(self) -> None:
        gate = PromotionGateEvaluation(
            gate_id="blocked-gate",
            configured_status="blocked_pending_approval",
            ready=False,
            blockers=("gate_status_not_approved",),
            missing_owner_roles=(),
            missing_thresholds=(),
            pending_artifacts=(),
        )
        enabled, status = assistant_availability(
            data_scope="production-shadow",
            runtime_flag_requested=True,
            promotion_gate=gate,
            local_live_shadow_acknowledged=True,
        )
        self.assertTrue(enabled)
        self.assertEqual(status, "enabled_for_local_shadow")


if __name__ == "__main__":
    unittest.main()
