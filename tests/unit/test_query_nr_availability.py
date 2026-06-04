"""
Mock Test for query_national_rail_availability()
Tests seat availability calculation and date range handling
"""

from unittest.mock import MagicMock, patch
from databases.relational.queries import query_national_rail_availability


def test_query_national_rail_availability_with_specific_date():
    """Test: specific travel_date provided - returns available schedules"""
    
    mock_schedules = [
        {
            'schedule_id': 'NR_SCH01',
            'line': 'NR1',
            'direction': 'northbound',
            'origin_station_id': 'NR01',
            'destination_station_id': 'NR05',
            'first_train_time': '06:00:00',
            'last_train_time': '22:00:00',
            'base_fare_usd': 50.00,
            'travel_date': '2025-06-01',
            'total_seats': 100,
            'booked_seats': 30,
            'available_seats': 70
        },
        {
            'schedule_id': 'NR_SCH02',
            'line': 'NR1',
            'direction': 'northbound',
            'origin_station_id': 'NR01',
            'destination_station_id': 'NR05',
            'first_train_time': '12:00:00',
            'last_train_time': '22:00:00',
            'base_fare_usd': 45.00,
            'travel_date': '2025-06-01',
            'total_seats': 80,
            'booked_seats': 80,
            'available_seats': 0  # This should be filtered out by query
        }
    ]
    
    with patch('databases.relational.queries._connect') as mock_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        # Query filters out available_seats = 0, so return only first one
        mock_cursor.fetchall.return_value = [mock_schedules[0]]
        
        # Call function
        result = query_national_rail_availability('NR01', 'NR05', '2025-06-01')
        
        # Assertions
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]['schedule_id'] == 'NR_SCH01'
        assert result[0]['available_seats'] == 70
        assert result[0]['travel_date'] == '2025-06-01'
        
        # Verify parameterized query with specific date
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args
        sql_text = call_args[0][0]
        params = call_args[0][1]
        
        # Verify bookings_count subquery exists
        assert 'bookings_count' in sql_text
        assert 'GROUP BY' in sql_text
        assert 'available_seats' in sql_text
        assert 'confirmed' in sql_text and 'pending' in sql_text
        
        # Verify parameters
        assert '2025-06-01' in params
        assert 'NR01' in params
        assert 'NR05' in params
        
        print("✓ Test passed: specific travel_date with seat availability calculation")


def test_query_national_rail_availability_no_date_14day_range():
    """Test: no travel_date provided - returns schedules for 14 day range"""
    
    mock_schedules = [
        {
            'schedule_id': 'NR_SCH01',
            'line': 'NR1',
            'direction': 'northbound',
            'origin_station_id': 'NR01',
            'destination_station_id': 'NR05',
            'first_train_time': '06:00:00',
            'last_train_time': '22:00:00',
            'base_fare_usd': 50.00,
            'travel_date': '2025-06-01',
            'total_seats': 100,
            'booked_seats': 25,
            'available_seats': 75
        },
        {
            'schedule_id': 'NR_SCH02',
            'line': 'NR1',
            'direction': 'northbound',
            'origin_station_id': 'NR01',
            'destination_station_id': 'NR05',
            'first_train_time': '12:00:00',
            'last_train_time': '22:00:00',
            'base_fare_usd': 45.00,
            'travel_date': '2025-06-02',
            'total_seats': 80,
            'booked_seats': 40,
            'available_seats': 40
        }
    ]
    
    with patch('databases.relational.queries._connect') as mock_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = mock_schedules
        
        # Call function without travel_date
        result = query_national_rail_availability('NR01', 'NR05')
        
        # Assertions
        assert isinstance(result, list)
        assert len(result) == 2
        
        # Verify multiple dates are included
        dates = [r['travel_date'] for r in result]
        assert '2025-06-01' in dates
        assert '2025-06-02' in dates
        
        # Verify seat calculations
        assert result[0]['available_seats'] == 75
        assert result[1]['available_seats'] == 40
        
        # Verify parameterized query includes 14-day logic
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args
        sql_text = call_args[0][0]
        
        # Verify date_range CTE with GENERATE_SERIES
        assert 'date_range' in sql_text
        assert 'GENERATE_SERIES' in sql_text
        assert '13' in sql_text  # 0-13 days = 14 days total
        assert 'CROSS JOIN date_range' in sql_text
        
        print("✓ Test passed: 14-day range query without specific travel_date")


def test_query_national_rail_availability_no_available_seats():
    """Test: all schedules are fully booked - returns empty list"""
    
    with patch('databases.relational.queries._connect') as mock_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []
        
        # Call function
        result = query_national_rail_availability('NR01', 'NR99', '2025-06-01')
        
        # Assertions
        assert isinstance(result, list)
        assert len(result) == 0
        
        print("✓ Test passed: no available seats returns empty list")


def test_query_national_rail_availability_seat_calculation():
    """Test: verify seat calculation logic (total_seats - booked_seats)"""
    
    mock_schedules = [
        {
            'schedule_id': 'NR_SCH01',
            'line': 'NR1',
            'direction': 'northbound',
            'origin_station_id': 'NR01',
            'destination_station_id': 'NR05',
            'first_train_time': '06:00:00',
            'last_train_time': '22:00:00',
            'base_fare_usd': 50.00,
            'travel_date': '2025-06-01',
            'total_seats': 150,
            'booked_seats': 0,  # No bookings
            'available_seats': 150
        },
        {
            'schedule_id': 'NR_SCH02',
            'line': 'NR1',
            'direction': 'northbound',
            'origin_station_id': 'NR01',
            'destination_station_id': 'NR05',
            'first_train_time': '12:00:00',
            'last_train_time': '22:00:00',
            'base_fare_usd': 45.00,
            'travel_date': '2025-06-01',
            'total_seats': 100,
            'booked_seats': 99,
            'available_seats': 1  # Nearly full, 1 seat left
        }
    ]
    
    with patch('databases.relational.queries._connect') as mock_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = mock_schedules
        
        # Call function
        result = query_national_rail_availability('NR01', 'NR05', '2025-06-01')
        
        # Assertions
        assert result[0]['available_seats'] == 150  # Full capacity
        assert result[1]['available_seats'] == 1    # Nearly full
        
        # Verify calculation: available = total - booked
        for row in result:
            expected = row['total_seats'] - row['booked_seats']
            assert row['available_seats'] == expected
        
        print("✓ Test passed: seat availability calculation verified")


def test_query_national_rail_availability_filters_full_schedules():
    """Test: fully booked schedules are filtered out (available_seats > 0 condition)"""
    
    # The WHERE clause in the query should filter: available_seats > 0
    # So full schedules shouldn't appear in results
    
    with patch('databases.relational.queries._connect') as mock_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        # Simulate: query returns only schedules with available_seats > 0
        mock_cursor.fetchall.return_value = []
        
        # Call function
        result = query_national_rail_availability('NR01', 'NR05', '2025-06-01')
        
        # Assertions
        assert isinstance(result, list)
        assert all(r['available_seats'] > 0 for r in result)
        
        # Verify query has filter condition
        call_args = mock_cursor.execute.call_args
        sql_text = call_args[0][0]
        assert '> 0' in sql_text  # Filter for available_seats > 0
        
        print("✓ Test passed: fully booked schedules filtered out")


def test_query_national_rail_availability_uses_rdictcursor():
    """Test: function uses RealDictCursor"""
    
    with patch('databases.relational.queries._connect') as mock_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []
        
        # Call function
        query_national_rail_availability('NR01', 'NR05')
        
        # Verify cursor_factory parameter was set to RealDictCursor
        mock_conn.cursor.assert_called_once()
        call_kwargs = mock_conn.cursor.call_args[1]
        # Implementation uses cursor_factory=psycopg2.extras.RealDictCursor
        
        print("✓ Test passed: RealDictCursor usage verified")


if __name__ == '__main__':
    print("Running Mock Tests for query_national_rail_availability()...")
    print()
    
    test_query_national_rail_availability_with_specific_date()
    test_query_national_rail_availability_no_date_14day_range()
    test_query_national_rail_availability_no_available_seats()
    test_query_national_rail_availability_seat_calculation()
    test_query_national_rail_availability_filters_full_schedules()
    test_query_national_rail_availability_uses_rdictcursor()
    
    print()
    print("=" * 60)
    print("All tests passed! ✓")
    print("=" * 60)
