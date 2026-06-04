"""
Test the query_delay_ripple function with BFS delay ripple analysis.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from databases.graph.queries import query_delay_ripple


def test_query_delay_ripple_basic():
    """Test basic delay ripple query with 2 hops."""
    print("\n" + "="*70)
    print("Test: query_delay_ripple (Basic - 2 hops)")
    print("="*70)
    
    # Test with a metro station (e.g., MS03)
    result = query_delay_ripple("MS03", hops=2)
    
    print(f"\nAffected Station: {result['affected_station']}")
    print(f"\nPrimary Impact Zone (1 hop away):")
    for station in result["primary_impact_zone"]:
        print(f"  - {station['station_id']}: {station['name']} ({station['hops_away']} hop)")
    
    print(f"\nSecondary Impact Zone (2+ hops away):")
    for station in result["secondary_impact_zone"]:
        print(f"  - {station['station_id']}: {station['name']} ({station['hops_away']} hops)")
    
    print(f"\nTotal Affected Stations: {result['total_affected_stations']}")
    print(f"Total Hops Searched: {result['total_hops_searched']}")
    
    # Verify DoD
    assert result["affected_station"] is not None, "✗ Center station should be found"
    assert isinstance(result["primary_impact_zone"], list), "✗ primary_impact_zone should be a list"
    assert isinstance(result["secondary_impact_zone"], list), "✗ secondary_impact_zone should be a list"
    
    # Verify all primary zone stations have exactly 1 hop
    for station in result["primary_impact_zone"]:
        assert station["hops_away"] == 1, f"✗ Primary zone station {station['station_id']} should have hops_away=1"
    
    # Verify all secondary zone stations have 2+ hops
    for station in result["secondary_impact_zone"]:
        assert station["hops_away"] >= 2, f"✗ Secondary zone station {station['station_id']} should have hops_away>=2"
    
    print("\n✓ All assertions passed!")


def test_query_delay_ripple_national_rail():
    """Test delay ripple query on national rail network."""
    print("\n" + "="*70)
    print("Test: query_delay_ripple (National Rail - 2 hops)")
    print("="*70)
    
    # Test with a national rail station (e.g., NR02)
    result = query_delay_ripple("NR02", hops=2)
    
    print(f"\nAffected Station: {result['affected_station']}")
    print(f"\nPrimary Impact Zone (1 hop away):")
    for station in result["primary_impact_zone"]:
        print(f"  - {station['station_id']}: {station['name']} ({station['hops_away']} hop)")
    
    print(f"\nSecondary Impact Zone (2+ hops away):")
    for station in result["secondary_impact_zone"]:
        print(f"  - {station['station_id']}: {station['name']} ({station['hops_away']} hops)")
    
    print(f"\nTotal Affected Stations: {result['total_affected_stations']}")
    
    # Verify DoD
    assert result["affected_station"] is not None, "✗ Center station should be found"
    assert result["affected_station"]["network_type"] == "national_rail", "✗ Should be national rail network"
    
    print("\n✓ All assertions passed!")


def test_query_delay_ripple_single_hop():
    """Test delay ripple with single hop only."""
    print("\n" + "="*70)
    print("Test: query_delay_ripple (Single Hop)")
    print("="*70)
    
    result = query_delay_ripple("MS01", hops=1)
    
    print(f"\nAffected Station: {result['affected_station']}")
    print(f"\nPrimary Impact Zone (1 hop away):")
    for station in result["primary_impact_zone"]:
        print(f"  - {station['station_id']}: {station['name']}")
    
    print(f"\nSecondary Impact Zone should be empty:")
    print(f"  Count: {len(result['secondary_impact_zone'])}")
    
    # Verify no secondary impact zone when hops=1
    assert len(result["secondary_impact_zone"]) == 0, "✗ No stations should be in secondary zone for hops=1"
    
    print("\n✓ All assertions passed!")


def test_query_delay_ripple_return_type():
    """Verify return type is dict with correct keys."""
    print("\n" + "="*70)
    print("Test: Return Type Verification")
    print("="*70)
    
    result = query_delay_ripple("MS03", hops=2)
    
    # Verify return type
    assert isinstance(result, dict), "✗ Return type should be dict"
    
    # Verify required keys
    required_keys = [
        "affected_station_id",
        "affected_station",
        "primary_impact_zone",
        "secondary_impact_zone",
        "total_affected_stations",
        "total_hops_searched"
    ]
    
    for key in required_keys:
        assert key in result, f"✗ Missing key: {key}"
    
    print(f"✓ All required keys present:")
    for key in required_keys:
        print(f"  - {key}: {type(result[key]).__name__}")
    
    print("\n✓ Return type verification passed!")


if __name__ == "__main__":
    try:
        test_query_delay_ripple_return_type()
        test_query_delay_ripple_basic()
        test_query_delay_ripple_national_rail()
        test_query_delay_ripple_single_hop()
        print("\n" + "="*70)
        print("✓ ALL TESTS PASSED!")
        print("="*70)
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
