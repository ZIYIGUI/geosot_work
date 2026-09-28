"""Offline v2 contract tests: no cryptographic or encoding correctness claims."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cell_contract as cc


PROFILE = dict(scheme_namespace="project:iwhere_legacy", scheme_version="1",
               crs="EPSG:4326", height_profile="legacy-height-v1", dimension=3)
WINDOW = {"valid_from": "2026-09-24T10:00:00+08:00", "valid_to": "2026-09-24T11:00:00+08:00"}


def observation(value=7.2, source="weather_a"):
    return cc.normalize_observation(
        {"attribute_id": "WX1", "name": "wind_speed", "type": "continuous", "value": value, "unit": "m/s"},
        dataset_id="dataset-a", source_id=source, source_record_id="record-1", default_interval=WINDOW)


class TestContract(unittest.TestCase):
    def test_v1_arrays_and_utc(self):
        value = cc.v1_to_v2({"grid": {"geo_num": "123456", "geo_level": 18}, "attributes": [
            {"attribute_id": "WX1", "type": "continuous", "name": "wind_speed", "value": 7.2, "unit": "m/s"}]},
            dataset_id="ds", source_id="wx", source_record_id="rec", default_interval=WINDOW, **PROFILE)
        self.assertEqual(value["schema_version"], "cell.v2")
        self.assertEqual(value["observations"][0]["valid_from"], "2026-09-24T02:00:00.000000Z")

    def test_existing_code_and_props_require_explicit_mapping(self):
        record = {"code": "123456-18", "level": 18, "dim": 3, "props": {"wind": 7.2}}
        args = dict(dataset_id="ds", source_id="wx", source_record_id="rec", default_interval=WINDOW, **PROFILE)
        with self.assertRaises(cc.ContractError):
            cc.v1_to_v2(record, **args)
        result = cc.v1_to_v2(record, property_specs={"wind": {"type": "continuous", "unit": "m/s"}}, **args)
        self.assertEqual(result["grid"]["geo_num"], "123456")
        self.assertEqual(result["observations"][0]["attribute_name"], "wind")

    def test_bad_identity_and_aliases(self):
        for record in ({"code": "123-17", "level": 18}, {"geo_num": "123", "level": 18, "geo_level": 19},
                       {"geo_num": "123", "level": True}, {"grid_code": "G18_T2026", "level": 18},
                       {"geo_num": "123", "level": 18, "dim": 2}):
            with self.subTest(record=record), self.assertRaises(cc.ContractError):
                cc.normalize_grid(record, **PROFILE)

    def test_unmapped_properties_are_not_silently_dropped(self):
        record = {"code": "123456-18", "level": 18, "dim": 3, "props": {"wind": 7.2, "temperature": 22}}
        with self.assertRaises(cc.ContractError) as caught:
            cc.v1_to_v2(record, dataset_id="ds", source_id="wx", source_record_id="rec",
                        default_interval=WINDOW, property_specs={"wind": {"type": "continuous", "unit": "m/s"}},
                        **PROFILE)
        self.assertEqual(caught.exception.code, "PROPERTY_MAPPING_REQUIRED")
        self.assertIn("temperature", str(caught.exception))

    def test_time_contract(self):
        for a, b in (("2026-09-24T10:00:00", "2026-09-24T11:00:00Z"),
                     ("2026-09-24T10:00:00Z", "2026-09-24T10:00:00Z")):
            with self.assertRaises(cc.ContractError):
                cc.normalize_interval(a, b)

    def test_strict_rfc3339_profile(self):
        invalid = ["2026-09-24 10:00:00Z", "2026-09-24T10:00Z", "2026-09-24t10:00:00z",
                   "2026-09-24T10:00:00+0800", "2026-09-24T10:00:00,12Z",
                   "2026-09-24T10:00:00.1234567Z", "2026-09-24T10:00:00-00:00",
                   "2026-09-24T10:00:00+00:99", "2026-09-24T10:00:60Z"]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(cc.ContractError):
                cc.parse_time(value)
        self.assertEqual(cc.utc_text("2026-09-24T10:00:00.123456+08:00"), "2026-09-24T02:00:00.123456Z")

    def test_multiple_sources_and_idempotency(self):
        a, b = observation(), observation(8.1, "weather_b")
        result = cc.append_observations([a], [a, b])
        self.assertEqual(len(result), 2)
        with self.assertRaises(cc.ContractError):
            cc.append_observations([a], [observation(9.1)])
        result[0]["value"] = 0
        self.assertEqual(a["value"], 7.2)

    def test_missing_invalid_numeric_source(self):
        for value in (None, True, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(cc.ContractError):
                observation(value)
        with self.assertRaises(cc.ContractError):
            cc.normalize_observation({"attribute_id": "a", "type": "continuous", "name": "wind", "value": 2,
                                      "unit": "m/s", "source": "forged"},
                                     dataset_id="d", source_id="actual", source_record_id="r", default_interval=WINDOW)

    def test_shared_key_ignores_dataset_identity_but_keeps_profiles(self):
        grid = cc.normalize_grid({"geo_num": "123", "level": 18}, **PROFILE)
        a = cc.canonical_cell_key({**grid, "dataset_id": "party_a"}, match_domain="task-01")
        b = cc.canonical_cell_key({**grid, "dataset_id": "party_b", "source_record_id": "different"}, match_domain="task-01")
        self.assertEqual(a, b)
        for field, value in (("scheme_version", "2"), ("height_profile", "other"), ("geo_level", 19)):
            self.assertNotEqual(a, cc.canonical_cell_key({**grid, field: value}, match_domain="task-01"))
        self.assertNotEqual(a, cc.canonical_cell_key(grid, match_domain="task-02"))

    def test_time_bins_half_open(self):
        grid = cc.normalize_grid({"geo_num": "123", "level": 18}, **PROFILE)
        profile = {"profile_id": "one-minute", "origin": "2026-09-24T00:00:00Z", "duration_seconds": 60}
        def index(at):
            return json.loads(cc.canonical_cell_key(grid, match_domain="task", time_bin_profile=profile, at=at))["time_bin_index"]
        self.assertEqual(index("2026-09-24T08:00:59.999999+08:00"), 0)
        self.assertEqual(index("2026-09-24T00:01:00Z"), 1)
        self.assertEqual(index("2026-09-23T23:59:59Z"), -1)
        with self.assertRaises(cc.ContractError):
            cc.canonical_cell_key(grid, match_domain="task", at="2026-09-24T00:00:00Z")

    def test_rule_unknown_conflict_and_boundary(self):
        args = dict(attribute_name="wind_speed", operator="GT", threshold=7, query_time="2026-09-24T02:30:00Z")
        self.assertEqual(cc.evaluate_local_condition([observation()], **args)["condition_state"], "TRUE")
        self.assertEqual(cc.evaluate_local_condition([], **args)["condition_state"], "UNKNOWN")
        self.assertEqual(cc.evaluate_local_condition([observation(), observation(8, "b")], **args)["condition_state"], "CONFLICT")
        args["query_time"] = "2026-09-24T03:00:00Z"
        self.assertEqual(cc.evaluate_local_condition([observation()], **args)["condition_state"], "UNKNOWN")

    def test_no_fake_cryptographic_execution(self):
        result = cc.describe_secure_operator("secure_compare", ["input:left", "input:right"], output_policy_id="decision-only")
        self.assertEqual(result["status"], "NOT_IMPLEMENTED")
        self.assertFalse(result["execution_supported"])
        self.assertNotIn("result", result)
        self.assertEqual(cc.describe_secure_operator("decrypt_anything", [], output_policy_id="none")["status"], "UNSUPPORTED")
        with self.assertRaises(cc.ContractError):
            cc.describe_secure_operator("secure_compare", [{"value": 7}, "input:right"], output_policy_id="decision-only")


if __name__ == "__main__":
    unittest.main()
