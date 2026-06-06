"""
Integration tests for query_interchange_path() against the live seeded Neo4j.

These run after seed_neo4j.py and hit the real graph, so they assert invariants
that hold for the seeded topology rather than a hard-coded station sequence
(apoc.algo.allSimplePaths does not guarantee a specific path). The seeded
interchange pairs are MS01<->NR01, MS07<->NR03, MS15<->NR07 (Central / Old Town
/ Ferndale).
"""

from databases.graph.queries import query_interchange_path

# Bidirectional interchange pairs present in the seed (both directions).
_INTERCHANGE_PAIRS = {("MS01", "NR01"), ("MS07", "NR03"), ("MS15", "NR07")}
_INTERCHANGE_PAIRS |= {(b, a) for (a, b) in _INTERCHANGE_PAIRS}


def _assert_valid_interchange_result(result, origin, destination):
    """Shared structural checks for a found cross-network path."""
    assert result["found"] is True, (
        f"expected an interchange path {origin}->{destination}, got {result.get('error')}"
    )
    assert result["origin_id"] == origin
    assert result["destination_id"] == destination

    ids = result["station_ids"]
    assert ids[0] == origin
    assert ids[-1] == destination

    # legs are contiguous and cover the whole path in order.
    legs = result["legs"]
    assert result["num_legs"] == len(legs) == len(ids) - 1
    for i, leg in enumerate(legs):
        assert leg["from_station_id"] == ids[i]
        assert leg["to_station_id"] == ids[i + 1]

    # at least one interchange, each crossing metro <-> national_rail via a real pair.
    interchanges = result["interchange_points"]
    assert len(interchanges) >= 1
    for ip in interchanges:
        assert {ip["from_network"], ip["to_network"]} == {"metro", "national_rail"}
        assert (ip["from_station_id"], ip["to_station_id"]) in _INTERCHANGE_PAIRS

    # every INTERCHANGE_TO leg must be surfaced as an interchange point.
    interchange_legs = [l for l in legs if l["relationship_type"] == "INTERCHANGE_TO"]
    assert len(interchange_legs) == len(interchanges)


def test_interchange_path_metro_to_rail():
    """Metro origin to national-rail destination crosses at least one interchange."""
    result = query_interchange_path("MS01", "NR02")
    _assert_valid_interchange_result(result, "MS01", "NR02")


def test_interchange_path_rail_to_metro():
    """National-rail origin to metro destination crosses at least one interchange."""
    result = query_interchange_path("NR05", "MS06")
    _assert_valid_interchange_result(result, "NR05", "MS06")


def test_interchange_path_uses_only_real_interchange_pairs():
    """Every interchange used must be one of the seeded interchange pairs."""
    result = query_interchange_path("MS02", "NR05")
    _assert_valid_interchange_result(result, "MS02", "NR05")
    used = {(ip["from_station_id"], ip["to_station_id"]) for ip in result["interchange_points"]}
    assert used <= _INTERCHANGE_PAIRS


def test_interchange_path_unknown_station_returns_not_found():
    """An unknown destination yields a well-formed found=False result, not a crash."""
    result = query_interchange_path("MS01", "ZZ99")
    assert result["found"] is False
    assert result["interchange_points"] == []
    assert result["station_ids"] == []
    assert result["error"]
