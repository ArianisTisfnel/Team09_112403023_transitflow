"""
Integration Test for query_available_seats()
Tests the complete workflow including JSON parsing and booking comparison
"""

from unittest.mock import MagicMock, patch
from databases.relational.queries import query_available_seats


def test_integration_complete_seat_availability():
    """
    Integration Test: Complete scenario with multiple coaches, bookings, and fare classes
    
    Scenario:
    - Schedule NR_SCH01 has 2 coaches (A: first class, B: standard class)
    - Coach A (first) has 6 seats, 1 booked
    - Coach B (standard) has 12 seats, 3 booked
    - Query for standard class seats on 2025-06-01
    - Expected: 9 available standard seats + 3 booked (unavailable)
    """
    
    # Real-world-like seat layout from train-mock-data
    mock_layout = {
        'layout_id': 'SL01',
        'schedule_id': 'NR_SCH01',
        'coaches': [
            {
                'coach': 'A',
                'fare_class': 'first',
                'seats': [
                    {'seat_id': 'A01', 'row': 1, 'column': 'A'},
                    {'seat_id': 'A02', 'row': 1, 'column': 'B'},
                    {'seat_id': 'A03', 'row': 2, 'column': 'A'},
                    {'seat_id': 'A04', 'row': 2, 'column': 'B'},
                    {'seat_id': 'A05', 'row': 3, 'column': 'A'},
                    {'seat_id': 'A06', 'row': 3, 'column': 'B'},
                ]
            },
            {
                'coach': 'B',
                'fare_class': 'standard',
                'seats': [
                    {'seat_id': 'B01', 'row': 1, 'column': 'A'},
                    {'seat_id': 'B02', 'row': 1, 'column': 'B'},
                    {'seat_id': 'B03', 'row': 1, 'column': 'C'},
                    {'seat_id': 'B04', 'row': 2, 'column': 'A'},
                    {'seat_id': 'B05', 'row': 2, 'column': 'B'},
                    {'seat_id': 'B06', 'row': 2, 'column': 'C'},
                    {'seat_id': 'B07', 'row': 3, 'column': 'A'},
                    {'seat_id': 'B08', 'row': 3, 'column': 'B'},
                    {'seat_id': 'B09', 'row': 3, 'column': 'C'},
                    {'seat_id': 'B10', 'row': 4, 'column': 'A'},
                    {'seat_id': 'B11', 'row': 4, 'column': 'B'},
                    {'seat_id': 'B12', 'row': 4, 'column': 'C'},
                ]
            }
        ],
        'total_seats': 18
    }
    
    # Real bookings from train-mock-data
    mock_bookings = [
        {'seat_id': 'B05'},  # From BK001
        {'seat_id': 'B03'},  # From BK003
        {'seat_id': 'B02'},  # Another booking
    ]
    
    with patch('databases.relational.queries._connect') as mock_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_cursor.fetchone.return_value = mock_layout
        mock_cursor.fetchall.return_value = mock_bookings
        
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn
        
        # Call the function for standard class
        result = query_available_seats('NR_SCH01', '2025-06-01', 'standard')
        
        # Validation 1: Correct number of seats
        print(f"✓ Returned {len(result)} seats (expected 12 standard class seats)")
        assert len(result) == 12, f"Expected 12 seats, got {len(result)}"
        
        # Validation 2: All seats are from coach B (standard class)
        coaches_in_result = {seat['coach'] for seat in result}
        assert coaches_in_result == {'B'}, f"Should only have coach B, got {coaches_in_result}"
        print(f"✓ All seats from correct coach: {coaches_in_result}")
        
        # Validation 3: JSON parsing successful (check for expected fields)
        for seat in result:
            required_fields = ['seat_id', 'coach', 'row', 'column', 'is_available']
            for field in required_fields:
                assert field in seat, f"Seat {seat.get('seat_id')} missing field {field}"
        print("✓ All seats have required fields: seat_id, coach, row, column, is_available")
        
        # Validation 4: Seat state comparison
        available_count = sum(1 for s in result if s['is_available'])
        unavailable_count = sum(1 for s in result if not s['is_available'])
        print(f"✓ Availability status: {available_count} available, {unavailable_count} booked")
        assert available_count == 9, f"Expected 9 available seats, got {available_count}"
        assert unavailable_count == 3, f"Expected 3 booked seats, got {unavailable_count}"
        
        # Validation 5: Verify booked seats are marked correctly
        booked_seat_ids = {'B02', 'B03', 'B05'}
        for seat in result:
            if seat['seat_id'] in booked_seat_ids:
                assert not seat['is_available'], f"Seat {seat['seat_id']} should be unavailable"
        print(f"✓ Booked seats correctly marked unavailable: {booked_seat_ids}")
        
        # Validation 6: Verify sort order (coach, row, column)
        seat_ids = [s['seat_id'] for s in result]
        expected_order = [
            'B01', 'B02', 'B03',
            'B04', 'B05', 'B06',
            'B07', 'B08', 'B09',
            'B10', 'B11', 'B12'
        ]
        assert seat_ids == expected_order, f"Seats not in correct order. Got {seat_ids}"
        print(f"✓ Seats correctly sorted by coach, row, column")
        
        print("\n✅ Integration test passed! DoD verification:")
        print("   [✓] 能夠成功解析 JSON 格式的 seat_map")
        print("   [✓] 成功比對並標示出每個座位的可用狀態")


if __name__ == '__main__':
    test_integration_complete_seat_availability()
