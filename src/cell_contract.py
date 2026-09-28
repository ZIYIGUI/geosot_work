"""Project v2 offline Cell contracts; NOT native iWhere APIs or cryptography.

The functions validate local data and describe secure-operator inputs. They do
not implement encryption, authentication, a database, or a secure executor.
Encoding and vertical-reference profiles must be supplied explicitly.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import math
import re
import unicodedata


class ContractError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ContractError("INVALID_FIELD", f"{name} must be nonempty text")
    if value != value.strip() or any(ord(c) < 32 for c in value):
        raise ContractError("INVALID_FIELD", f"{name} contains surrounding/control whitespace")
    return unicodedata.normalize("NFC", value)


def _integer(value, name, minimum=0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError("INVALID_FIELD", f"{name} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        raise ContractError("INVALID_FIELD", f"{name} outside permitted range")
    return value


def _alias(mapping, names, *, required=False):
    values = [mapping[n] for n in names if n in mapping]
    if values and any(value != values[0] for value in values[1:]):
        raise ContractError("CONFLICTING_ALIASES", "/".join(names))
    if not values:
        if required:
            raise ContractError("MISSING_FIELD", "/".join(names))
        return None
    return values[0]


def parse_time(value):
    """Parse the project's RFC3339 profile with explicit known UTC offset.

    Uppercase T/Z and seconds are required. Fractional seconds have at most
    microsecond precision; leap seconds and RFC3339 unknown offset -00:00 are
    outside this prototype's supported profile and are rejected explicitly.
    """
    value = _text(value, "timestamp")
    pattern = (r"[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
               r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])")
    if re.fullmatch(pattern, value) is None or value.endswith("-00:00"):
        raise ContractError("INVALID_TIME", "expected project RFC3339 profile with known offset")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("INVALID_TIME", value) from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ContractError("TIMEZONE_REQUIRED", value)
    return result.astimezone(timezone.utc)


def utc_text(value):
    return parse_time(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def normalize_interval(valid_from, valid_to):
    start, end = parse_time(valid_from), parse_time(valid_to)
    if start >= end:
        raise ContractError("INVALID_INTERVAL", "expected valid_from < valid_to")
    return {"valid_from": utc_text(valid_from), "valid_to": utc_text(valid_to)}


def _interval(record, default=None):
    nested = record.get("valid_time")
    if nested is not None and not isinstance(nested, dict):
        raise ContractError("INVALID_INTERVAL", "instant valid_time cannot imply an interval")
    combined = dict(record)
    if nested:
        for old, new in (("from", "valid_from"), ("to", "valid_to")):
            if old in nested:
                if new in combined and combined[new] != nested[old]:
                    # Offset-equivalent aliases are accepted, contradictory times are not.
                    if parse_time(combined[new]) != parse_time(nested[old]):
                        raise ContractError("CONFLICTING_ALIASES", new)
                combined[new] = nested[old]
    start, end = combined.get("valid_from"), combined.get("valid_to")
    if start is None and end is None and default is not None:
        return normalize_interval(default["valid_from"], default["valid_to"])
    if start is None or end is None:
        raise ContractError("MISSING_INTERVAL", "supply both validity boundaries")
    return normalize_interval(start, end)


def normalize_grid(record, *, scheme_namespace, scheme_version, crs, height_profile, dimension=None):
    """Read v1 grid/geo_num or repository code='decimal-level' records.

    This is identity normalization only; code validity against a particular
    encoding algorithm remains the encoding backend's responsibility.
    """
    grid = record.get("grid", record)
    if not isinstance(grid, dict):
        raise ContractError("INVALID_GRID", "grid must be an object")
    declared_dimension = _alias(grid, ("dimension", "dim"))
    if declared_dimension is not None and dimension is not None and declared_dimension != dimension:
        raise ContractError("DIMENSION_MISMATCH", "record and profile dimensions differ")
    dimension = dimension if dimension is not None else declared_dimension
    _integer(dimension, "dimension", 2, 3)
    level = _alias(grid, ("geo_level", "level"), required=True)
    _integer(level, "geo_level", 0, 32)
    code = _alias(grid, ("geo_num", "code"), required=True)
    if isinstance(code, int) and not isinstance(code, bool):
        if code < 0:
            raise ContractError("INVALID_CODE", "negative numeric code")
        code = str(code)
    code = _text(code, "geo_num")
    suffix = re.fullmatch(r"([0-9]+)-([0-9]+)", code)
    if suffix:
        if int(suffix.group(2)) != level:
            raise ContractError("LEVEL_MISMATCH", "code suffix and level differ")
        code = suffix.group(1)
    return {
        "scheme_namespace": _text(scheme_namespace, "scheme_namespace"),
        "scheme_version": _text(scheme_version, "scheme_version"),
        "dimension": dimension,
        "geo_level": level,
        "geo_num": code,
        "crs": _text(crs, "crs"),
        "height_profile": _text(height_profile, "height_profile"),
    }


def normalize_observation(raw, *, dataset_id, source_id, source_record_id,
                          default_interval=None, default_kind=None):
    """Normalize one source assertion; never merge different providers."""
    if not isinstance(raw, dict):
        raise ContractError("INVALID_OBSERVATION", "observation must be an object")
    kind = _alias(raw, ("type", "attribute_type", "value_kind")) or default_kind
    if kind not in ("continuous", "discrete"):
        raise ContractError("UNSUPPORTED_ATTRIBUTE", "only continuous/discrete observations")
    name = _text(_alias(raw, ("name", "attribute_name"), required=True), "attribute name")
    oid = _text(_alias(raw, ("observation_id", "attribute_id"), required=True), "observation id")
    declared_source = raw.get("source")
    if declared_source is not None and declared_source != source_id:
        raise ContractError("SOURCE_MISMATCH", "source must match authenticated ingestion context")
    status = raw.get("value_status", "KNOWN")
    if status not in ("KNOWN", "UNKNOWN"):
        raise ContractError("INVALID_STATUS", "value_status must be KNOWN or UNKNOWN")
    value = _alias(raw, ("value", "state"))
    unit = raw.get("unit")
    if status == "KNOWN":
        if kind == "continuous":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ContractError("INVALID_VALUE", "known continuous value must be finite numeric")
            unit = _text(unit, "unit")
        elif value is None or not isinstance(value, (str, int, bool)):
            raise ContractError("INVALID_VALUE", "known discrete value must be a scalar state")
    elif value is not None:
        raise ContractError("INVALID_VALUE", "UNKNOWN must not carry an invented value")
    confidence = raw.get("confidence")
    if confidence is not None:
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ContractError("INVALID_CONFIDENCE", "expected finite value in [0,1]")
    return {
        "dataset_id": _text(dataset_id, "dataset_id"),
        "source_id": _text(source_id, "source_id"),
        "source_record_id": _text(source_record_id, "source_record_id"),
        "observation_id": oid,
        "revision": _integer(raw.get("revision", 1), "revision", 1),
        "attribute_name": name,
        "value_kind": kind,
        "value_status": status,
        "value": value,
        "unit": unit,
        "confidence": confidence,
        **_interval(raw, default_interval),
    }


def v1_to_v2(record, *, dataset_id, source_id, source_record_id,
             scheme_namespace, scheme_version, crs, height_profile,
             dimension=None, default_interval=None, property_specs=None):
    """Adapt documented v1 arrays or typed repository 'props' to v2.

    All items must originate from this one ingestion source. Mixed-source
    containers must be split by their actual provider before ingestion.
    property_specs explicitly maps repository props names to kind/unit; no
    units, validity, or measurement provenance are guessed.
    """
    if "properties" in record:
        raise ContractError("UNSUPPORTED_LEGACY_SHAPE", "nested properties needs a source-specific mapper")
    attrs, states = record.get("attributes", []), record.get("states", [])
    if not isinstance(attrs, list) or not isinstance(states, list):
        raise ContractError("INVALID_ATTRIBUTES", "attributes/states must be arrays")
    items = [(a, "continuous") for a in attrs] + [(s, "discrete") for s in states]
    props = record.get("props", {})
    if props:
        if not isinstance(props, dict) or not property_specs:
            raise ContractError("PROPERTY_MAPPING_REQUIRED", "provide explicit property_specs")
        unmapped = set(props) - set(property_specs)
        if unmapped:
            raise ContractError("PROPERTY_MAPPING_REQUIRED", "unmapped props: " + ", ".join(sorted(unmapped)))
        for name, spec in property_specs.items():
            if name not in props:
                continue
            items.append(({
                "attribute_id": f"{source_record_id}:{name}", "name": name,
                "type": spec["type"], "unit": spec.get("unit"), "value": props[name],
            }, spec["type"]))
    normalized = [normalize_observation(
        raw, dataset_id=dataset_id, source_id=source_id, source_record_id=source_record_id,
        default_interval=default_interval, default_kind=kind) for raw, kind in items]
    return {
        "schema_version": "cell.v2",
        "dataset_id": _text(dataset_id, "dataset_id"),
        "grid": normalize_grid(record, scheme_namespace=scheme_namespace,
                               scheme_version=scheme_version, crs=crs, height_profile=height_profile,
                               dimension=dimension),
        "observations": append_observations([], normalized),
    }


def append_observations(existing, incoming):
    """Pure-function idempotent append; different sources are never overwritten."""
    result, seen = [], {}
    for item in list(existing) + list(incoming):
        key = tuple(item[k] for k in ("dataset_id", "source_id", "source_record_id", "observation_id", "revision"))
        if key in seen:
            if item != seen[key]:
                raise ContractError("REVISION_CONFLICT", "same source revision carries different data")
            continue
        copy = deepcopy(item)
        seen[key] = copy
        result.append(copy)
    return result


def canonical_cell_key(grid, *, match_domain, time_bin_profile=None, at=None):
    """Unencrypted canonical JSON bytes for an agreed PSI/MPC input contract.

    Dataset/provider/record IDs are deliberately excluded from a shared spatial
    matching key. These bytes are NOT privacy-preserving tokens. Do not publish
    them as encrypted data. Mixed levels/overlapping intervals need extra logic.
    """
    normalized = normalize_grid(grid, scheme_namespace=grid["scheme_namespace"],
                                scheme_version=grid["scheme_version"], crs=grid["crs"],
                                height_profile=grid["height_profile"], dimension=grid["dimension"])
    profile, index = None, None
    if time_bin_profile is not None:
        if at is None:
            raise ContractError("MISSING_TIME", "temporal matching requires at")
        duration = _integer(time_bin_profile["duration_seconds"], "duration_seconds", 1)
        origin = parse_time(time_bin_profile["origin"])
        instant = parse_time(at)
        index = (instant - origin) // timedelta(seconds=duration)
        profile = {
            "profile_id": _text(time_bin_profile["profile_id"], "time_bin_profile.profile_id"),
            "origin": utc_text(time_bin_profile["origin"]), "duration_seconds": duration,
            "boundary": "[from,to)",
        }
    elif at is not None:
        raise ContractError("TIME_PROFILE_REQUIRED", "at without time-bin profile is ambiguous")
    payload = {
        "schema_version": "cellkey.v2", "match_domain": _text(match_domain, "match_domain"),
        "grid": normalized, "time_bin_profile": profile, "time_bin_index": index,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def evaluate_local_condition(observations, *, attribute_name, operator, threshold, query_time):
    """Local-only, explicit four-state condition. This does NOT grant flight permission.

    Multiple unresolved source values yield CONFLICT; missing/expired values
    yield UNKNOWN. Secret predicates must use a real secure backend instead.
    """
    comparisons = {"EQ": lambda a, b: a == b, "GT": lambda a, b: a > b,
                   "GTE": lambda a, b: a >= b, "LT": lambda a, b: a < b,
                   "LTE": lambda a, b: a <= b}
    if operator not in comparisons:
        raise ContractError("UNSUPPORTED_OPERATOR", operator)
    when = parse_time(query_time)
    active = [o for o in observations if o["attribute_name"] == attribute_name
              and parse_time(o["valid_from"]) <= when < parse_time(o["valid_to"])]
    if not active or any(o["value_status"] != "KNOWN" for o in active):
        return {"condition_state": "UNKNOWN", "scope": "local_only"}
    if any((o["value_kind"], o["unit"], o["value"]) !=
           (active[0]["value_kind"], active[0]["unit"], active[0]["value"]) for o in active[1:]):
        return {"condition_state": "CONFLICT", "scope": "local_only"}
    if isinstance(threshold, float) and not math.isfinite(threshold):
        raise ContractError("INVALID_THRESHOLD", "threshold must be finite")
    if operator != "EQ" and (active[0]["value_kind"] != "continuous" or isinstance(threshold, bool)
                              or not isinstance(threshold, (int, float))):
        raise ContractError("TYPE_MISMATCH", "ordered comparisons need numeric inputs")
    if operator == "EQ":
        value = active[0]["value"]
        if isinstance(value, bool) != isinstance(threshold, bool):
            raise ContractError("TYPE_MISMATCH", "boolean and numeric values are distinct")
        if active[0]["value_kind"] == "continuous" and not isinstance(threshold, (int, float)):
            raise ContractError("TYPE_MISMATCH", "numeric equality needs a numeric threshold")
        if active[0]["value_kind"] == "discrete" and type(value) is not type(threshold):
            raise ContractError("TYPE_MISMATCH", "discrete equality needs the same scalar type")
    state = "TRUE" if comparisons[operator](active[0]["value"], threshold) else "FALSE"
    return {"condition_state": state, "scope": "local_only"}


SECURE_OPERATOR_CONTRACTS = {
    "secure_set_intersection": (2, None),
    "secure_compare": (2, 2),
    "secure_weighted_sum": (2, None),
    "secure_boolean_aggregate": (1, None),
}


def describe_secure_operator(operator, input_handles, *, output_policy_id):
    """Describe opaque inputs, explicitly declining to fake secure execution."""
    if operator not in SECURE_OPERATOR_CONTRACTS:
        return {"status": "UNSUPPORTED", "operator": operator, "execution_supported": False}
    if not isinstance(input_handles, list):
        raise ContractError("INVALID_HANDLES", "input_handles must be a list")
    minimum, maximum = SECURE_OPERATOR_CONTRACTS[operator]
    if len(input_handles) < minimum or (maximum is not None and len(input_handles) > maximum):
        raise ContractError("INVALID_ARITY", operator)
    handles = [_text(h, "opaque input handle") for h in input_handles]
    return {
        "status": "NOT_IMPLEMENTED", "execution_supported": False,
        "operator": operator, "input_handles": handles,
        "output_policy_id": _text(output_policy_id, "output_policy_id"),
        "reason": "No cryptographic engine connected; metadata only, no result computed.",
    }
