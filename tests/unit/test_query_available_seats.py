"""
Test for query_available_seats()
Tests seat availability calculation with JSON seat layout parsing and booking comparison
"""

from unittest.mock import MagicMock, patch
from databases.relational.queries import query_available_seats
import json


def test_query_available_seats_standard_class():
    """Test: query standard class seats for a schedule with some booked seats"""
    
    # Mock seat layout with multiple coaches
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
                ]
            }
        ],
        'total_seats': 10
    }
    
    # Mock booked seats (B02, B05)
    mock_bookings = [
        {'seat_id': 'B02'},
        {'seat_id': 'B05'}
    ]
    
    with patch('databases.relational.queries._connect') as mock_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        # Configure cursor to return layout first, then bookings
        mock_cursor.fetchone.return_value = mock_layout
        mock_cursor.fetchall.return_value = mock_bookings
        
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn
        
        # Call the function
        result = query_available_seats('NR_SCH01', '2025-06-01', 'standard')
        
        # Assertions
        assert isinstance(result, list), "Should return a list"
        assert len(result) == 6, f"Should have 6 standard class seats, got {len(result)}"
        
        # Check that all seats are from coach B
        for seat in result:
            assert seat['coach'] == 'B', f"All seats should be from coach B, got {seat['coach']}"
        
        # Check booked seats are marked as unavailable
        b02_seat = next((s for s in result if s['seat_id'] == 'B02'), None)
        b05_seat = next((s for s in result if s['seat_id'] == 'B05'), None)
        
        assert b02_seat is not None, "Should have seat B02"
        assert b05_seat is not None, "Should have seat B05"
        assert b02_seat['is_available'] is False, "B02 should be unavailable"
        assert b05_seat['is_available'] is False, "B05 should be unavailable"
        
        # Check available seats
        b01_seat = next((s for s in result if s['seat_id'] == 'B01'), None)
        assert b01_seat is not None, "Should have seat B01"
        assert b01_seat['is_available'] is True, "B01 should be available"
        
        print("✓ Standard class seats query test passed")


def test_query_available_seats_first_class():
    """Test: query first class seats only"""
    
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
                ]
            },
            {
                'coach': 'B',
                'fare_class': 'standard',
                'seats': [
                    {'seat_id': 'B01', 'row': 1, 'column': 'A'},
                    {'seat_id': 'B02', 'row': 1, 'column': 'B'},
                ]
            }
        ],
        'total_seats': 5
    }
    
    mock_bookings = [
        {'seat_id': 'A02'}
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
        
        result = query_available_seats('NR_SCH01', '2025-06-01', 'first')
        
        assert len(result) == 3, f"Should have 3 first class seats, got {len(result)}"
        for seat in result:
            assert seat['coach'] == 'A', f"All seats should be from coach A"
        
        # Check A02 is booked
        a02_seat = next((s for s in result if s['seat_id'] == 'A02'), None)
        assert a02_seat['is_available'] is False, "A02 should be unavailable"
        
        print("✓ First class seats query test passed")


def test_query_available_seats_no_layout():
    """Test: schedule_id does not exist - should return empty list"""
    
    with patch('databases.relational.queries._connect') as mock_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_cursor.fetchone.return_value = None  # No layout found
        
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn
        
        result = query_available_seats('INVALID_SCH', '2025-06-01', 'standard')
        
        assert isinstance(result, list), "Should return a list"
        assert len(result) == 0, "Should return empty list for non-existent schedule"
        
        print("✓ No layout test passed")


def test_query_available_seats_no_matching_fare_class():
    """Test: no coaches match the requested fare_class - should return empty list"""
    
    mock_layout = {
        'layout_id': 'SL01',
        'schedule_id': 'NR_SCH01',
        'coaches': [
            {
                'coach': 'A',
                'fare_class': 'first',
                'seats': [
                    {'seat_id': 'A01', 'row': 1, 'column': 'A'},
                ]
            }
        ],
        'total_seats': 1
    }
    
    with patch('databases.relational.queries._connect') as mock_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_cursor.fetchone.return_value = mock_layout
        
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn
        
        result = query_available_seats('NR_SCH01', '2025-06-01', 'standard')
        
        assert len(result) == 0, "Should return empty list when no fare_class matches"
        
        print("✓ No matching fare class test passed")


def test_query_available_seats_sort_order():
    """Test: seats are sorted by coach, row, column"""
    
    mock_layout = {
        'layout_id': 'SL01',
        'schedule_id': 'NR_SCH01',
        'coaches': [
            {
                'coach': 'B',
                'fare_class': 'standard',
                'seats': [
                    {'seat_id': 'B02', 'row': 2, 'column': 'B'},
                    {'seat_id': 'B01', 'row': 1, 'column': 'A'},
                    {'seat_id': 'B03', 'row': 2, 'column': 'C'},
                ]
            },
            {
                'coach': 'A',
                'fare_class': 'standard',
                'seats': [
                    {'seat_id': 'A02', 'row': 2, 'column': 'B'},
                    {'seat_id': 'A01', 'row': 1, 'column': 'A'},
                ]
            }
        ],
        'total_seats': 5
    }
    
    mock_bookings = []
    
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
        
        result = query_available_seats('NR_SCH01', '2025-06-01', 'standard')
        
        # Expected order: A1, A2, B1, B2, B3
        seat_ids = [s['seat_id'] for s in result]
        expected_order = ['A01', 'A02', 'B01', 'B02', 'B03']
        
        assert seat_ids == expected_order, f"Seats should be sorted by coach, row, column. Got {seat_ids}"
        
        print("✓ Sort order test passed")


if __name__ == '__main__':
    test_query_available_seats_standard_class()
    test_query_available_seats_first_class()
    test_query_available_seats_no_layout()
    test_query_available_seats_no_matching_fare_class()
    test_query_available_seats_sort_order()
    print("\n✅ All tests passed!")
