"""
Test for execute_cancellation()
Tests state machine validation, transaction rollback, and audit timestamp recording
"""

from unittest.mock import MagicMock, patch
from databases.relational.queries import execute_cancellation
from datetime import datetime, timezone


def test_execute_cancellation_success_pending_status():
    """Test: successfully cancel a booking with 'pending' status"""
    
    mock_booking = {
        'booking_id': 'BK-TEST001',
        'user_id': 'RU01',
        'status': 'pending',
        'amount_usd': 50.00,
        'booked_at': '2026-05-18T10:00:00+00:00'
    }
    
    with patch('databases.relational.queries.psycopg2.connect') as mock_psycopg2_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        # Configure cursor to return booking
        mock_cursor.fetchone.return_value = mock_booking
        mock_cursor.rowcount = 1  # One row updated
        
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_psycopg2_connect.return_value = mock_conn
        
        with patch('databases.relational.queries._gen_payment_id', return_value='PM-TEST001'):
            success, result = execute_cancellation(
                booking_id='BK-TEST001',
                reason='Customer requested'
            )
        
        # Verify success
        assert success is True, f"Cancellation should succeed, got error: {result}"
        assert isinstance(result, dict), "Result should be a dict on success"
        
        # Verify cancellation details
        assert result['booking_id'] == 'BK-TEST001'
        assert result['status'] == 'cancelled'
        assert result['original_amount_usd'] == 50.00
        assert result['cancellation_reason'] == 'Customer requested'
        assert 'cancelled_at' in result
        assert 'cancellation_timestamp_utc' in result
        assert result['original_status'] == 'pending'
        
        # Verify commit was called
        mock_conn.commit.assert_called_once()
        
        # Verify no rollback was called
        mock_conn.rollback.assert_not_called()
        
        print("✓ Successful cancellation of pending booking test passed")


def test_execute_cancellation_success_confirmed_status():
    """Test: successfully cancel a booking with 'confirmed' status"""
    
    mock_booking = {
        'booking_id': 'BK-TEST002',
        'user_id': 'RU02',
        'status': 'confirmed',
        'amount_usd': 75.50,
        'booked_at': '2026-05-17T14:00:00+00:00'
    }
    
    with patch('databases.relational.queries.psycopg2.connect') as mock_psycopg2_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_cursor.fetchone.return_value = mock_booking
        mock_cursor.rowcount = 1
        
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_psycopg2_connect.return_value = mock_conn
        
        with patch('databases.relational.queries._gen_payment_id', return_value='PM-TEST002'):
            success, result = execute_cancellation(
                booking_id='BK-TEST002',
                reason='Schedule changed'
            )
        
        assert success is True, "Cancellation should succeed"
        assert result['original_status'] == 'confirmed'
        assert result['cancellation_reason'] == 'Schedule changed'
        
        print("✓ Successful cancellation of confirmed booking test passed")


def test_execute_cancellation_reject_completed_status():
    """Test: reject cancellation of 'completed' booking - state machine validation"""
    
    mock_booking = {
        'booking_id': 'BK-TEST003',
        'user_id': 'RU03',
        'status': 'completed',
        'amount_usd': 100.00,
        'booked_at': '2026-04-10T09:00:00+00:00'
    }
    
    with patch('databases.relational.queries.psycopg2.connect') as mock_psycopg2_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_cursor.fetchone.return_value = mock_booking
        
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_psycopg2_connect.return_value = mock_conn
        
        success, result = execute_cancellation(
            booking_id='BK-TEST003',
            reason='Customer changed mind'
        )
        
        # Verify rejection
        assert success is False, "Cancellation should be rejected"
        assert isinstance(result, str), "Result should be error message"
        assert 'completed' in result.lower(), f"Error should mention completed status: {result}"
        assert 'cannot cancel' in result.lower(), f"Error should mention rejection: {result}"
        
        # Verify rollback was called (state validation failed before any update)
        mock_conn.rollback.assert_called()
        
        # Verify no commit was called
        mock_conn.commit.assert_not_called()
        
        print("✓ Rejection of completed booking test passed")


def test_execute_cancellation_reject_already_cancelled_status():
    """Test: reject cancellation of already 'cancelled' booking"""
    
    mock_booking = {
        'booking_id': 'BK-TEST004',
        'user_id': 'RU04',
        'status': 'cancelled',
        'amount_usd': 60.00,
        'booked_at': '2026-05-10T12:00:00+00:00'
    }
    
    with patch('databases.relational.queries.psycopg2.connect') as mock_psycopg2_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_cursor.fetchone.return_value = mock_booking
        
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_psycopg2_connect.return_value = mock_conn
        
        success, result = execute_cancellation(
            booking_id='BK-TEST004'
        )
        
        assert success is False, "Cancellation should be rejected"
        assert 'cancelled' in result.lower(), "Error should mention cancelled status"
        
        print("✓ Rejection of already cancelled booking test passed")


def test_execute_cancellation_booking_not_found():
    """Test: booking does not exist - should fail early"""
    
    with patch('databases.relational.queries.psycopg2.connect') as mock_psycopg2_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        # No booking found
        mock_cursor.fetchone.return_value = None
        
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_psycopg2_connect.return_value = mock_conn
        
        success, result = execute_cancellation(booking_id='INVALID_BK')
        
        assert success is False, "Cancellation should fail"
        assert 'not found' in result.lower(), f"Error should mention booking not found: {result}"
        
        print("✓ Booking not found test passed")


def test_execute_cancellation_default_reason():
    """Test: default cancellation reason when none provided"""
    
    mock_booking = {
        'booking_id': 'BK-TEST005',
        'user_id': 'RU05',
        'status': 'pending',
        'amount_usd': 45.00,
        'booked_at': '2026-05-18T11:00:00+00:00'
    }
    
    with patch('databases.relational.queries.psycopg2.connect') as mock_psycopg2_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_cursor.fetchone.return_value = mock_booking
        mock_cursor.rowcount = 1
        
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_psycopg2_connect.return_value = mock_conn
        
        with patch('databases.relational.queries._gen_payment_id', return_value='PM-TEST005'):
            # Call without explicit reason - should use default
            success, result = execute_cancellation(booking_id='BK-TEST005')
        
        assert success is True
        assert result['cancellation_reason'] == 'Customer requested'
        
        print("✓ Default cancellation reason test passed")


def test_execute_cancellation_transaction_rollback_on_db_error():
    """Test: database error triggers rollback"""
    
    import psycopg2
    
    mock_booking = {
        'booking_id': 'BK-TEST006',
        'user_id': 'RU06',
        'status': 'pending',
        'amount_usd': 55.00,
        'booked_at': '2026-05-18T15:00:00+00:00'
    }
    
    with patch('databases.relational.queries.psycopg2.connect') as mock_psycopg2_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        # First fetch succeeds, but execute fails
        mock_cursor.fetchone.return_value = mock_booking
        mock_cursor.execute.side_effect = [
            None,  # SELECT booking
            psycopg2.Error("Constraint violation")  # UPDATE fails
        ]
        
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_psycopg2_connect.return_value = mock_conn
        
        success, result = execute_cancellation(booking_id='BK-TEST006')
        
        assert success is False, "Cancellation should fail due to database error"
        
        # Verify rollback was called
        mock_conn.rollback.assert_called()
        
        # Verify connection was closed
        mock_conn.close.assert_called()
        
        print("✓ Transaction rollback on DB error test passed")


def test_execute_cancellation_audit_timestamp_utc():
    """Test: cancelled_at timestamp is recorded in UTC"""
    
    mock_booking = {
        'booking_id': 'BK-TEST007',
        'user_id': 'RU07',
        'status': 'pending',
        'amount_usd': 70.00,
        'booked_at': '2026-05-18T08:00:00+00:00'
    }
    
    with patch('databases.relational.queries.psycopg2.connect') as mock_psycopg2_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_cursor.fetchone.return_value = mock_booking
        mock_cursor.rowcount = 1
        
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_psycopg2_connect.return_value = mock_conn
        
        with patch('databases.relational.queries._gen_payment_id', return_value='PM-TEST007'):
            success, result = execute_cancellation(booking_id='BK-TEST007')
        
        assert success is True
        
        # Verify cancelled_at is present and is a valid ISO format timestamp
        assert 'cancelled_at' in result
        assert 'cancellation_timestamp_utc' in result
        
        # Both should be ISO format with timezone info (UTC)
        cancelled_at_iso = result['cancelled_at']
        utc_iso = result['cancellation_timestamp_utc']
        
        # Verify it's ISO format with timezone
        assert '+00:00' in cancelled_at_iso or 'Z' in cancelled_at_iso, \
            f"cancelled_at should be UTC: {cancelled_at_iso}"
        assert '+00:00' in utc_iso or 'Z' in utc_iso, \
            f"cancellation_timestamp_utc should be UTC: {utc_iso}"
        
        # Parse and verify it's a valid datetime
        try:
            parsed_dt = datetime.fromisoformat(cancelled_at_iso.replace('Z', '+00:00'))
            assert parsed_dt.tzinfo is not None, "Should have timezone info"
        except ValueError:
            assert False, f"Invalid ISO format: {cancelled_at_iso}"
        
        print("✓ Audit timestamp UTC recording test passed")


if __name__ == '__main__':
    test_execute_cancellation_success_pending_status()
    test_execute_cancellation_success_confirmed_status()
    test_execute_cancellation_reject_completed_status()
    test_execute_cancellation_reject_already_cancelled_status()
    test_execute_cancellation_booking_not_found()
    test_execute_cancellation_default_reason()
    test_execute_cancellation_transaction_rollback_on_db_error()
    test_execute_cancellation_audit_timestamp_utc()
    print("\n✅ All execute_cancellation tests passed!")
