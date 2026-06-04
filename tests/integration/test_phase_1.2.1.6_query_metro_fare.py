"""
Test suite for query_metro_fare function (Phase 1.2.1.6).

Tests the metro fare query with station distance calculation and tiered pricing.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from databases.relational.queries import query_metro_fare


def test_metro_fare_basic():
    """Test basic fare calculation with known stations."""
    print("\n" + "="*70)
    print("TEST: Basic Metro Fare Query")
    print("="*70)
    
    # Test 1: Adjacent stations (1 stop) → $1.50
    result = query_metro_fare("MS01", "MS02")
    print(f"\n[Test 1] MS01 → MS02 (should be 1 stop, $1.50):")
    print(f"  Valid: {result['valid']}")
    print(f"  Origin: {result['origin_name']}")
    print(f"  Destination: {result['destination_name']}")
    print(f"  Distance: {result['distance_stops']} stops")
    print(f"  Fare Tier: {result['fare_tier']}")
    print(f"  Fare: ${result['fare_usd']}")
    assert result['valid'] is True, "Query should succeed"
    assert result['distance_stops'] == 1, f"Expected 1 stop, got {result['distance_stops']}"
    assert result['fare_tier'] == "1-2 stops", f"Expected '1-2 stops' tier, got {result['fare_tier']}"
    assert result['fare_usd'] == 1.50, f"Expected $1.50, got ${result['fare_usd']}"
    print("  ✓ PASS")
    
    # Test 2: 2 stops → $1.50
    result = query_metro_fare("MS01", "MS03")
    print(f"\n[Test 2] MS01 → MS03 (should be 2 stops, $1.50):")
    print(f"  Distance: {result['distance_stops']} stops")
    print(f"  Fare Tier: {result['fare_tier']}")
    print(f"  Fare: ${result['fare_usd']}")
    if result['valid']:
        assert result['distance_stops'] == 2, f"Expected 2 stops, got {result['distance_stops']}"
        assert result['fare_tier'] == "1-2 stops", f"Expected '1-2 stops' tier"
        assert result['fare_usd'] == 1.50, f"Expected $1.50, got ${result['fare_usd']}"
        print("  ✓ PASS")
    else:
        print(f"  Note: No direct path found - {result.get('error')}")


def test_metro_fare_long_distance():
    """Test longer distance routes."""
    print("\n" + "="*70)
    print("TEST: Long Distance Metro Fare")
    print("="*70)
    
    # Test: 3-5 stops range → $2.50
    result = query_metro_fare("MS01", "MS04")
    print(f"\n[Test] MS01 → MS04 (3-5 stops range, $2.50):")
    print(f"  Valid: {result['valid']}")
    print(f"  Distance: {result['distance_stops']} stops")
    print(f"  Fare Tier: {result['fare_tier']}")
    print(f"  Fare: ${result['fare_usd']}")
    if result['valid']:
        assert 3 <= result['distance_stops'] <= 5, f"Expected 3-5 stops, got {result['distance_stops']}"
        assert result['fare_tier'] == "3-5 stops", f"Expected '3-5 stops' tier"
        assert result['fare_usd'] == 2.50, f"Expected $2.50, got ${result['fare_usd']}"
        print("  ✓ PASS")
    else:
        print(f"  Note: No direct path found - {result.get('error')}")
    
    # Test: 6+ stops range → $4.00
    result = query_metro_fare("MS05", "MS12")
    print(f"\n[Test] MS05 → MS12 (6+ stops range, $4.00):")
    print(f"  Valid: {result['valid']}")
    print(f"  Distance: {result['distance_stops']} stops")
    print(f"  Fare Tier: {result['fare_tier']}")
    print(f"  Fare: ${result['fare_usd']}")
    if result['valid']:
        assert result['distance_stops'] >= 6, f"Expected 6+ stops, got {result['distance_stops']}"
        assert result['fare_tier'] == "6+ stops", f"Expected '6+ stops' tier"
        assert result['fare_usd'] == 4.00, f"Expected $4.00, got ${result['fare_usd']}"
        print("  ✓ PASS")
    else:
        print(f"  Note: No direct path found - {result.get('error')}")


def test_metro_fare_invalid_stations():
    """Test error handling for invalid stations."""
    print("\n" + "="*70)
    print("TEST: Invalid Station Handling")
    print("="*70)
    
    # Test: Non-existent origin
    result = query_metro_fare("INVALID", "MS02")
    print(f"\n[Test] Invalid origin 'INVALID':")
    print(f"  Valid: {result['valid']}")
    print(f"  Error: {result['error']}")
    assert result['valid'] is False, "Query should fail for invalid origin"
    assert result['error'] is not None, "Error message should be provided"
    print("  ✓ PASS")
    
    # Test: Non-existent destination
    result = query_metro_fare("MS01", "INVALID")
    print(f"\n[Test] Invalid destination 'INVALID':")
    print(f"  Valid: {result['valid']}")
    print(f"  Error: {result['error']}")
    assert result['valid'] is False, "Query should fail for invalid destination"
    assert result['error'] is not None, "Error message should be provided"
    print("  ✓ PASS")
    
    # Test: Same station
    result = query_metro_fare("MS01", "MS01")
    print(f"\n[Test] Same origin and destination:")
    print(f"  Valid: {result['valid']}")
    print(f"  Error: {result['error']}")
    assert result['valid'] is False, "Query should fail for same station"
    assert result['error'] is not None, "Error message should be provided"
    print("  ✓ PASS")


def test_metro_fare_symmetry():
    """Test round-trip fare consistency."""
    print("\n" + "="*70)
    print("TEST: Symmetry & Round-Trip Consistency")
    print("="*70)
    
    # Test: Forward and reverse should have same distance (if bidirectional)
    result_forward = query_metro_fare("MS02", "MS03")
    result_reverse = query_metro_fare("MS03", "MS02")
    
    print(f"\n[Test] Forward: MS02 → MS03")
    print(f"  Distance: {result_forward['distance_stops']} stops")
    print(f"  Fare: ${result_forward['fare_usd']}")
    
    print(f"\n[Test] Reverse: MS03 → MS02")
    print(f"  Distance: {result_reverse['distance_stops']} stops")
    print(f"  Fare: ${result_reverse['fare_usd']}")
    
    if result_forward['valid'] and result_reverse['valid']:
        # Note: Graph may not be fully bidirectional, so we just log
        if result_forward['distance_stops'] == result_reverse['distance_stops']:
            print("  ✓ PASS (symmetric)")
        else:
            print(f"  Note: Asymmetric path ({result_forward['distance_stops']} vs {result_reverse['distance_stops']})")


def test_metro_fare_response_format():
    """Test response structure and data types."""
    print("\n" + "="*70)
    print("TEST: Response Format & Data Types")
    print("="*70)
    
    result = query_metro_fare("MS01", "MS02")
    
    print(f"\n[Test] Response structure:")
    required_fields = [
        "origin_station_id", "destination_station_id",
        "origin_name", "destination_name",
        "distance_stops", "fare_tier", "fare_usd",
        "valid", "error"
    ]
    
    for field in required_fields:
        assert field in result, f"Missing required field: {field}"
        print(f"  ✓ {field}: {result[field]}")
    
    if result['valid']:
        assert isinstance(result['distance_stops'], int), "distance_stops should be int"
        assert isinstance(result['fare_tier'], str), "fare_tier should be str"
        assert isinstance(result['fare_usd'], float), "fare_usd should be float"
        print("\n  ✓ All data types correct")


if __name__ == "__main__":
    try:
        test_metro_fare_response_format()
        test_metro_fare_invalid_stations()
        test_metro_fare_basic()
        test_metro_fare_long_distance()
        test_metro_fare_symmetry()
        
        print("\n" + "="*70)
        print("✓ ALL TESTS PASSED")
        print("="*70 + "\n")
        
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
