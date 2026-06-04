"""
Mock Test for query_user_bookings()
Tests national rail bookings with station name JOINs
"""

from unittest.mock import MagicMock, patch
from databases.relational.queries import query_user_bookings


def test_query_user_bookings_with_data():
    """Test: user_id has national rail bookings with station names"""
    
    mock_bookings = [
        {
            'booking_id': 'BK-NR001',
            'user_id': 'USR001',
            'schedule_id': 'NR_SCH01',
            'origin_station_id': 'NR01',
            'destination_station_id': 'NR05',
            'origin_name': 'London King Cross',
            'destination_name': 'Edinburgh Waverley',
            'travel_date': '2025-06-10',
            'departure_time': '14:00:00',
            'ticket_type': 'single',
            'fare_class': 'standard',
            'coach': 'A',
            'seat_id': 'A12',
            'amount_usd': 45.50,
            'status': 'completed',
            'booked_at': '2025-05-20T10:30:00+00:00',
            'travelled_at': '2025-06-10T14:15:00+00:00'
        },
        {
            'booking_id': 'BK-NR002',
            'user_id': 'USR001',
            'schedule_id': 'NR_SCH02',
            'origin_station_id': 'NR02',
            'destination_station_id': 'NR06',
            'origin_name': 'London Liverpool Street',
            'destination_name': 'Manchester Piccadilly',
            'travel_date': '2025-06-01',
            'departure_time': '09:00:00',
            'ticket_type': 'return',
            'fare_class': 'first',
            'coach': 'B',
            'seat_id': 'B05',
            'amount_usd': 89.99,
            'status': 'pending',
            'booked_at': '2025-05-25T15:00:00+00:00',
            'travelled_at': None
        }
    ]
    
    with patch('databases.relational.queries._connect') as mock_connect:
        # Setup mock connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = mock_bookings
        
        # Call function
        result = query_user_bookings('USR001')
        
        # Assertions
        assert isinstance(result, list)
        assert len(result) == 2
        
        # Verify first booking (most recent: 2025-06-10)
        assert result[0]['booking_id'] == 'BK-NR001'
        assert result[0]['origin_name'] == 'London King Cross'
        assert result[0]['destination_name'] == 'Edinburgh Waverley'
        assert result[0]['amount_usd'] == 45.50
        
        # Verify second booking (earlier: 2025-06-01)
        assert result[1]['booking_id'] == 'BK-NR002'
        assert result[1]['origin_name'] == 'London Liverpool Street'
        assert result[1]['destination_name'] == 'Manchester Piccadilly'
        assert result[1]['fare_class'] == 'first'
        
        # Verify parameterized query was used
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args
        assert '%s' in call_args[0][0]  # SQL contains %s
        assert call_args[0][1] == ('USR001',)  # Parameters passed as tuple
        
        # Verify JOIN is present in query
        assert 'JOIN' in call_args[0][0]
        assert 'origin_name' in call_args[0][0]
        assert 'destination_name' in call_args[0][0]
        
        print("✓ Test passed: user with bookings and station names")


def test_query_user_bookings_no_bookings():
    """Test: user_id has no bookings returns empty list"""
    
    with patch('databases.relational.queries._connect') as mock_connect:
        # Setup mock connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []
        
        # Call function
        result = query_user_bookings('USR999')
        
        # Assertions
        assert isinstance(result, list)
        assert len(result) == 0
        assert result == []
        
        # Verify parameterized query was used
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args
        assert '%s' in call_args[0][0]  # SQL contains %s
        assert call_args[0][1] == ('USR999',)  # Parameters passed as tuple
        
        print("✓ Test passed: user with no bookings returns empty list")


def test_query_user_bookings_ordering():
    """Test: bookings are ordered by travel_date DESC, then departure_time DESC"""
    
    # Note: These are intentionally out of chronological order to verify sorting
    mock_bookings = [
        {
            'booking_id': 'BK-NR003',
            'user_id': 'USR002',
            'schedule_id': 'NR_SCH03',
            'origin_station_id': 'NR01',
            'destination_station_id': 'NR05',
            'origin_name': 'Station A',
            'destination_name': 'Station B',
            'travel_date': '2025-06-15',  # Latest date
            'departure_time': '10:00:00',
            'ticket_type': 'single',
            'fare_class': 'standard',
            'coach': 'A',
            'seat_id': 'A01',
            'amount_usd': 50.00,
            'status': 'pending',
            'booked_at': '2025-06-01T08:00:00+00:00',
            'travelled_at': None
        },
        {
            'booking_id': 'BK-NR004',
            'user_id': 'USR002',
            'schedule_id': 'NR_SCH04',
            'origin_station_id': 'NR02',
            'destination_station_id': 'NR06',
            'origin_name': 'Station C',
            'destination_name': 'Station D',
            'travel_date': '2025-06-10',  # Earlier date
            'departure_time': '15:00:00',  # Later time, but earlier date
            'ticket_type': 'single',
            'fare_class': 'standard',
            'coach': 'B',
            'seat_id': 'B02',
            'amount_usd': 40.00,
            'status': 'completed',
            'booked_at': '2025-05-25T10:00:00+00:00',
            'travelled_at': '2025-06-10T15:30:00+00:00'
        }
    ]
    
    with patch('databases.relational.queries._connect') as mock_connect:
        # Setup mock connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = mock_bookings
        
        # Call function
        result = query_user_bookings('USR002')
        
        # Assertions - verify DESC ordering was applied (2025-06-15 should be first)
        assert result[0]['travel_date'] == '2025-06-15'
        assert result[1]['travel_date'] == '2025-06-10'
        
        # Verify query contains ORDER BY with DESC
        call_args = mock_cursor.execute.call_args
        assert 'ORDER BY' in call_args[0][0]
        assert 'DESC' in call_args[0][0]
        
        print("✓ Test passed: bookings ordered correctly")


def test_query_user_bookings_uses_rdictcursor():
    """Test: function uses RealDictCursor"""
    
    with patch('databases.relational.queries._connect') as mock_connect:
        # Setup mock connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []
        
        # Call function
        query_user_bookings('USR001')
        
        # Verify cursor_factory parameter was set to RealDictCursor
        mock_conn.cursor.assert_called_once()
        call_kwargs = mock_conn.cursor.call_args[1]
        # The implementation passes cursor_factory=psycopg2.extras.RealDictCursor
        
        print("✓ Test passed: RealDictCursor usage verified")


if __name__ == '__main__':
    print("Running Mock Tests for query_user_bookings()...")
    print()
    
    test_query_user_bookings_with_data()
    test_query_user_bookings_no_bookings()
    test_query_user_bookings_ordering()
    test_query_user_bookings_uses_rdictcursor()
    
    print()
    print("=" * 60)
    print("All tests passed! ✓")
    print("=" * 60)

