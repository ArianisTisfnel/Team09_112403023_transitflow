"""
Test for execute_booking()
Tests transactional integrity, conflict detection, and dual-table writes
"""

from unittest.mock import MagicMock, patch, call
from databases.relational.queries import execute_booking
from datetime import datetime, timezone


def test_execute_booking_success():
    """Test: successful booking with explicit seat selection"""
    
    mock_schedule = {
        'schedule_id': 'NR_SCH01',
        'first_train_time': '07:00:00',
        'base_fare_usd': 50.00
    }
    
    # No existing booking for this seat
    mock_existing_booking = None
    
    with patch('databases.relational.queries.psycopg2.connect') as mock_psycopg2_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        # Configure cursor to return appropriate responses
        mock_cursor.fetchone.side_effect = [
            {'user_id': 'RU01'},  # User exists
            mock_schedule,         # Schedule found
            mock_existing_booking  # No existing booking for this seat
        ]
        
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_psycopg2_connect.return_value = mock_conn
        
        # Mock the _gen_booking_id and _gen_payment_id to return predictable IDs
        with patch('databases.relational.queries._gen_booking_id', return_value='BK-TEST001'):
            with patch('databases.relational.queries._gen_payment_id', return_value='PM-TEST001'):
                success, result = execute_booking(
                    user_id='RU01',
                    schedule_id='NR_SCH01',
                    origin_station_id='NR01',
                    destination_station_id='NR05',
                    travel_date='2025-06-01',
                    fare_class='standard',
                    seat_id='B05',
                    ticket_type='single'
                )
        
        # Verify success
        assert success is True, f"Booking should succeed, got error: {result}"
        assert isinstance(result, dict), "Result should be a dict on success"
        
        # Verify booking details
        assert result['booking_id'] == 'BK-TEST001'
        assert result['payment_id'] == 'PM-TEST001'
        assert result['user_id'] == 'RU01'
        assert result['seat_id'] == 'B05'
        assert result['coach'] == 'B'
        assert result['total_fare_usd'] == 50.00  # standard class: 50 * 1.0
        assert result['status'] == 'pending'
        
        # Verify commit was called
        mock_conn.commit.assert_called_once()
        
        # Verify no rollback was called
        mock_conn.rollback.assert_not_called()
        
        print("✓ Successful booking test passed")


def test_execute_booking_seat_conflict():
    """Test: seat is already booked - should detect conflict and reject"""
    
    mock_schedule = {
        'schedule_id': 'NR_SCH01',
        'first_train_time': '07:00:00',
        'base_fare_usd': 50.00
    }
    
    # Existing booking for this seat
    mock_existing_booking = {
        'booking_id': 'BK-EXISTING',
        'seat_id': 'B05',
        'coach': 'B'
    }
    
    with patch('databases.relational.queries.psycopg2.connect') as mock_psycopg2_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_cursor.fetchone.side_effect = [
            {'user_id': 'RU01'},      # User exists
            mock_schedule,             # Schedule found
            mock_existing_booking      # Existing booking found - CONFLICT!
        ]
        
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_psycopg2_connect.return_value = mock_conn
        
        success, result = execute_booking(
            user_id='RU01',
            schedule_id='NR_SCH01',
            origin_station_id='NR01',
            destination_station_id='NR05',
            travel_date='2025-06-01',
            fare_class='standard',
            seat_id='B05'
        )
        
        # Verify failure
        assert success is False, "Booking should fail due to conflict"
        assert isinstance(result, str), "Result should be error message"
        assert 'already booked' in result.lower(), f"Error should mention conflict: {result}"
        
        # Verify rollback was called
        mock_conn.rollback.assert_called()
        
        # Verify no commit was called
        mock_conn.commit.assert_not_called()
        
        print("✓ Seat conflict detection test passed")


def test_execute_booking_user_not_found():
    """Test: user_id does not exist - should fail early"""
    
    with patch('databases.relational.queries.psycopg2.connect') as mock_psycopg2_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        # User not found
        mock_cursor.fetchone.return_value = None
        
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_psycopg2_connect.return_value = mock_conn
        
        success, result = execute_booking(
            user_id='INVALID_USER',
            schedule_id='NR_SCH01',
            origin_station_id='NR01',
            destination_station_id='NR05',
            travel_date='2025-06-01',
            fare_class='standard',
            seat_id='B05'
        )
        
        assert success is False, "Booking should fail"
        assert 'not found' in result.lower(), f"Error should mention user not found: {result}"
        
        print("✓ User not found test passed")


def test_execute_booking_fare_class_multiplier():
    """Test: fare multiplier is correctly applied based on fare_class"""
    
    mock_schedule = {
        'schedule_id': 'NR_SCH01',
        'first_train_time': '07:00:00',
        'base_fare_usd': 100.00
    }
    
    # Test different fare classes
    test_cases = [
        ('standard', 1.0, 100.00),
        ('first', 1.5, 150.00),
        ('senior', 0.8, 80.00),
        ('student', 0.85, 85.00),
    ]
    
    for fare_class, expected_multiplier, expected_fare in test_cases:
        with patch('databases.relational.queries.psycopg2.connect') as mock_psycopg2_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            
            mock_cursor.fetchone.side_effect = [
                {'user_id': 'RU01'},  # User exists
                mock_schedule,         # Schedule found
                None                   # No existing booking
            ]
            
            mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
            mock_cursor.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_psycopg2_connect.return_value = mock_conn
            
            with patch('databases.relational.queries._gen_booking_id', return_value='BK-TEST'):
                with patch('databases.relational.queries._gen_payment_id', return_value='PM-TEST'):
                    success, result = execute_booking(
                        user_id='RU01',
                        schedule_id='NR_SCH01',
                        origin_station_id='NR01',
                        destination_station_id='NR05',
                        travel_date='2025-06-01',
                        fare_class=fare_class,
                        seat_id='B05'
                    )
            
            assert success is True, f"Booking should succeed for {fare_class}"
            assert result['fare_multiplier'] == expected_multiplier, \
                f"Expected multiplier {expected_multiplier} for {fare_class}"
            assert result['total_fare_usd'] == expected_fare, \
                f"Expected fare {expected_fare} for {fare_class}"
    
    print("✓ Fare multiplier test passed for all classes")


def test_execute_booking_transaction_rollback():
    """Test: database error triggers rollback"""
    
    import psycopg2
    
    mock_schedule = {
        'schedule_id': 'NR_SCH01',
        'first_train_time': '07:00:00',
        'base_fare_usd': 50.00
    }
    
    with patch('databases.relational.queries.psycopg2.connect') as mock_psycopg2_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        # First two fetchone calls succeed, but execute fails on INSERT
        mock_cursor.fetchone.side_effect = [
            {'user_id': 'RU01'},  # User exists
            mock_schedule,         # Schedule found
            None                   # No existing booking
        ]
        
        # Simulate database error on execute (INSERT)
        mock_cursor.execute.side_effect = [
            None,  # SELECT user_id
            None,  # SELECT schedule
            None,  # SELECT conflict check
            psycopg2.Error("Database constraint violation")  # INSERT booking fails
        ]
        
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_psycopg2_connect.return_value = mock_conn
        
        with patch('databases.relational.queries._gen_booking_id', return_value='BK-TEST'):
            success, result = execute_booking(
                user_id='RU01',
                schedule_id='NR_SCH01',
                origin_station_id='NR01',
                destination_station_id='NR05',
                travel_date='2025-06-01',
                fare_class='standard',
                seat_id='B05'
            )
        
        assert success is False, "Booking should fail due to database error"
        assert isinstance(result, str), "Result should be error message"
        
        # Verify rollback was called
        mock_conn.rollback.assert_called()
        
        # Verify connection was closed
        mock_conn.close.assert_called()
        
        print("✓ Transaction rollback test passed")


def test_execute_booking_dual_table_writes():
    """Test: both national_rail_bookings and payments tables are written"""
    
    mock_schedule = {
        'schedule_id': 'NR_SCH01',
        'first_train_time': '07:00:00',
        'base_fare_usd': 50.00
    }
    
    with patch('databases.relational.queries.psycopg2.connect') as mock_psycopg2_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_cursor.fetchone.side_effect = [
            {'user_id': 'RU01'},  # User exists
            mock_schedule,         # Schedule found
            None                   # No existing booking
        ]
        
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_psycopg2_connect.return_value = mock_conn
        
        with patch('databases.relational.queries._gen_booking_id', return_value='BK-TEST'):
            with patch('databases.relational.queries._gen_payment_id', return_value='PM-TEST'):
                success, result = execute_booking(
                    user_id='RU01',
                    schedule_id='NR_SCH01',
                    origin_station_id='NR01',
                    destination_station_id='NR05',
                    travel_date='2025-06-01',
                    fare_class='standard',
                    seat_id='B05'
                )
        
        # Verify execute was called multiple times for INSERT operations
        execute_calls = mock_cursor.execute.call_args_list
        
        # Should have: SELECT user, SELECT schedule, SELECT conflict, INSERT booking, INSERT payment
        assert len(execute_calls) >= 5, f"Expected at least 5 execute calls, got {len(execute_calls)}"
        
        # Find the INSERT statements
        insert_calls = [call for call in execute_calls if 'INSERT' in str(call)]
        assert len(insert_calls) == 2, f"Should have 2 INSERT calls (booking + payment), got {len(insert_calls)}"
        
        # Verify one INSERT is for national_rail_bookings
        booking_insert_found = any('national_rail_bookings' in str(call) for call in insert_calls)
        assert booking_insert_found, "Should have INSERT into national_rail_bookings"
        
        # Verify one INSERT is for payments
        payment_insert_found = any('payments' in str(call) for call in insert_calls)
        assert payment_insert_found, "Should have INSERT into payments"
        
        print("✓ Dual table writes test passed")


if __name__ == '__main__':
    test_execute_booking_success()
    test_execute_booking_seat_conflict()
    test_execute_booking_user_not_found()
    test_execute_booking_fare_class_multiplier()
    test_execute_booking_transaction_rollback()
    test_execute_booking_dual_table_writes()
    print("\n✅ All execute_booking tests passed!")
