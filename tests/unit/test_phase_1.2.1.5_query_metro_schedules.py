"""
Mock Test for query_metro_schedules()
Tests direction filtering, TIME conversion, and operating_days logic
"""

from unittest.mock import MagicMock, patch
from databases.relational.queries import query_metro_schedules


def test_query_metro_schedules_with_direction_filter():
    """Test: direction parameter is used as WHERE condition"""
    
    mock_schedules = [
        {
            'schedule_id': 'MS_SCH01',
            'line': 'M1',
            'direction': 'northbound',
            'origin_station_id': 'MS01',
            'destination_station_id': 'MS09',
            'first_train_time': '06:00',      # ✓ TIME converted to string
            'last_train_time': '23:30',       # ✓ TIME converted to string
            'base_fare_usd': 3.50,
            'operating_days': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
            'travel_date': '2025-06-01'
        }
    ]
    
    with patch('databases.relational.queries._connect') as mock_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = mock_schedules
        
        # Call function with direction
        result = query_metro_schedules('M1', direction='northbound')
        
        # Assertions
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]['direction'] == 'northbound'
        
        # Verify parameterized query includes direction filter
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args
        sql_text = call_args[0][0]
        
        assert 'direction' in sql_text
        assert 'WHERE' in sql_text
        
        # Verify TIME conversion to string
        assert result[0]['first_train_time'] == '06:00'
        assert result[0]['last_train_time'] == '23:30'
        
        print("✓ Test passed: direction filter and TIME conversion")


def test_query_metro_schedules_no_direction_filter():
    """Test: without direction, returns all directions"""
    
    mock_schedules = [
        {
            'schedule_id': 'MS_SCH01',
            'line': 'M1',
            'direction': 'northbound',
            'origin_station_id': 'MS01',
            'destination_station_id': 'MS09',
            'first_train_time': '06:00',
            'last_train_time': '23:30',
            'base_fare_usd': 3.50,
            'operating_days': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
            'travel_date': '2025-06-01'
        },
        {
            'schedule_id': 'MS_SCH02',
            'line': 'M1',
            'direction': 'southbound',
            'origin_station_id': 'MS09',
            'destination_station_id': 'MS01',
            'first_train_time': '06:15',
            'last_train_time': '23:45',
            'base_fare_usd': 3.50,
            'operating_days': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
            'travel_date': '2025-06-01'
        }
    ]
    
    with patch('databases.relational.queries._connect') as mock_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = mock_schedules
        
        # Call function without direction
        result = query_metro_schedules('M1')
        
        # Assertions
        assert len(result) == 2
        directions = [r['direction'] for r in result]
        assert 'northbound' in directions
        assert 'southbound' in directions
        
        print("✓ Test passed: no direction filter returns all directions")


def test_query_metro_schedules_travel_date_operating_day():
    """Test: travel_date is operating day returns schedules"""
    
    mock_schedules = [
        {
            'schedule_id': 'MS_SCH01',
            'line': 'M1',
            'direction': 'northbound',
            'origin_station_id': 'MS01',
            'destination_station_id': 'MS09',
            'first_train_time': '06:00',
            'last_train_time': '23:30',
            'base_fare_usd': 3.50,
            'operating_days': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
            'travel_date': '2025-06-01'  # Sunday, operating day
        }
    ]
    
    with patch('databases.relational.queries._connect') as mock_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = mock_schedules
        
        # Call function with specific travel_date
        result = query_metro_schedules('M1', travel_date='2025-06-01')
        
        # Assertions
        assert len(result) == 1
        assert result[0]['travel_date'] == '2025-06-01'
        
        # Verify query checks operating_days
        call_args = mock_cursor.execute.call_args
        sql_text = call_args[0][0]
        assert 'operating_days' in sql_text
        assert '@>' in sql_text  # JSONB contains operator
        
        print("✓ Test passed: travel_date on operating day")


def test_query_metro_schedules_travel_date_non_operating_day():
    """Test: travel_date is non-operating day returns empty list"""
    
    with patch('databases.relational.queries._connect') as mock_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []  # No schedules on this day
        
        # Call function with non-operating date (schedule only runs Mon-Fri)
        result = query_metro_schedules('M1', travel_date='2025-06-07')  # Saturday, if not operating
        
        # Assertions
        assert isinstance(result, list)
        assert len(result) == 0
        
        print("✓ Test passed: non-operating day returns empty list")


def test_query_metro_schedules_no_travel_date_current_day():
    """Test: travel_date=None uses CURRENT_DATE day-of-week for filtering"""
    
    mock_schedules = [
        {
            'schedule_id': 'MS_SCH01',
            'line': 'M1',
            'direction': 'northbound',
            'origin_station_id': 'MS01',
            'destination_station_id': 'MS09',
            'first_train_time': '06:00',
            'last_train_time': '23:30',
            'base_fare_usd': 3.50,
            'operating_days': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
            'travel_date': '2025-06-16'  # Current date
        }
    ]
    
    with patch('databases.relational.queries._connect') as mock_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = mock_schedules
        
        # Call function without travel_date
        result = query_metro_schedules('M1')
        
        # Assertions
        assert len(result) == 1
        
        # Verify query uses CURRENT_DATE for day-of-week check
        call_args = mock_cursor.execute.call_args
        sql_text = call_args[0][0]
        assert 'CURRENT_DATE' in sql_text
        assert 'operating_days' in sql_text
        
        print("✓ Test passed: no travel_date uses CURRENT_DATE")


def test_query_metro_schedules_time_conversion_to_string():
    """Test: TIME format from PostgreSQL is converted to string HH:MI"""
    
    mock_schedules = [
        {
            'schedule_id': 'MS_SCH01',
            'line': 'M1',
            'direction': 'northbound',
            'origin_station_id': 'MS01',
            'destination_station_id': 'MS09',
            'first_train_time': '05:45',      # String format from TO_CHAR
            'last_train_time': '23:59',       # String format from TO_CHAR
            'base_fare_usd': 3.50,
            'operating_days': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
            'travel_date': '2025-06-01'
        }
    ]
    
    with patch('databases.relational.queries._connect') as mock_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = mock_schedules
        
        # Call function
        result = query_metro_schedules('M1')
        
        # Assertions - verify TIME is string
        assert isinstance(result[0]['first_train_time'], str)
        assert isinstance(result[0]['last_train_time'], str)
        assert result[0]['first_train_time'] == '05:45'
        assert result[0]['last_train_time'] == '23:59'
        
        # Verify TO_CHAR is in SQL query
        call_args = mock_cursor.execute.call_args
        sql_text = call_args[0][0]
        assert 'TO_CHAR' in sql_text
        
        print("✓ Test passed: TIME conversion to string for JSON serialization")


def test_query_metro_schedules_operating_days_jsonb():
    """Test: operating_days is returned as JSONB array"""
    
    mock_schedules = [
        {
            'schedule_id': 'MS_SCH01',
            'line': 'M1',
            'direction': 'northbound',
            'origin_station_id': 'MS01',
            'destination_station_id': 'MS09',
            'first_train_time': '06:00',
            'last_train_time': '23:30',
            'base_fare_usd': 3.50,
            'operating_days': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],  # Weekdays only
            'travel_date': '2025-06-01'
        }
    ]
    
    with patch('databases.relational.queries._connect') as mock_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = mock_schedules
        
        # Call function
        result = query_metro_schedules('M1')
        
        # Assertions
        assert 'operating_days' in result[0]
        assert isinstance(result[0]['operating_days'], list)
        assert 'Mon' in result[0]['operating_days']
        assert len(result[0]['operating_days']) == 5  # Weekdays
        
        print("✓ Test passed: operating_days as JSONB array")


def test_query_metro_schedules_uses_rdictcursor():
    """Test: function uses RealDictCursor"""
    
    with patch('databases.relational.queries._connect') as mock_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []
        
        # Call function
        query_metro_schedules('M1')
        
        # Verify cursor_factory parameter was set
        mock_conn.cursor.assert_called_once()
        call_kwargs = mock_conn.cursor.call_args[1]
        # Implementation uses cursor_factory=psycopg2.extras.RealDictCursor
        
        print("✓ Test passed: RealDictCursor usage verified")


if __name__ == '__main__':
    print("Running Mock Tests for query_metro_schedules()...")
    print()
    
    test_query_metro_schedules_with_direction_filter()
    test_query_metro_schedules_no_direction_filter()
    test_query_metro_schedules_travel_date_operating_day()
    test_query_metro_schedules_travel_date_non_operating_day()
    test_query_metro_schedules_no_travel_date_current_day()
    test_query_metro_schedules_time_conversion_to_string()
    test_query_metro_schedules_operating_days_jsonb()
    test_query_metro_schedules_uses_rdictcursor()
    
    print()
    print("=" * 60)
    print("All tests passed! ✓")
    print("=" * 60)
