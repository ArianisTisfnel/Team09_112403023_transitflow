"""
Integration Test for execute_cancellation()
Tests complete cancellation workflow including state machine and audit trail
"""

from unittest.mock import MagicMock, patch
from databases.relational.queries import execute_cancellation
from datetime import datetime, timezone


def test_integration_complete_cancellation_workflow():
    """
    Integration Test: Complete cancellation workflow
    
    Scenario:
    - User has pending booking BK-TEST001 (amount: $50.00)
    - Cancellation reason: "Schedule conflict"
    - System should:
      1. Verify booking exists
      2. Validate state is 'pending' (allowed)
      3. Update status to 'cancelled'
      4. Record cancellation_reason
      5. Record cancelled_at with UTC timestamp
      6. Create payment record for audit
      7. Commit transaction
    """
    
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
        
        # Configure cursor responses
        mock_cursor.fetchone.return_value = mock_booking
        mock_cursor.rowcount = 1
        
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_psycopg2_connect.return_value = mock_conn
        
        with patch('databases.relational.queries._gen_payment_id', return_value='PM-CANCEL001'):
            success, result = execute_cancellation(
                booking_id='BK-TEST001',
                reason='Schedule conflict'
            )
        
        print("✓ Cancellation initiated for booking BK-TEST001")
        
        # Validation 1: Success status
        assert success is True, f"Cancellation should succeed, got error: {result}"
        print("✓ Cancellation succeeded")
        
        # Validation 2: Required fields present
        required_fields = [
            'booking_id', 'original_amount_usd', 'status',
            'cancelled_at', 'cancellation_reason',
            'cancellation_timestamp_utc', 'original_status'
        ]
        for field in required_fields:
            assert field in result, f"Result missing field: {field}"
        print(f"✓ All {len(required_fields)} audit fields present")
        
        # Validation 3: State machine transition
        assert result['original_status'] == 'pending', "Original status should be pending"
        assert result['status'] == 'cancelled', "New status should be cancelled"
        print("✓ State machine transition: pending → cancelled")
        
        # Validation 4: Audit information
        assert result['cancellation_reason'] == 'Schedule conflict'
        print("✓ Cancellation reason recorded: 'Schedule conflict'")
        
        # Validation 5: Timestamp verification
        cancelled_at = result['cancelled_at']
        assert isinstance(cancelled_at, str), "cancelled_at should be string"
        assert '+00:00' in cancelled_at or 'Z' in cancelled_at, "Should be UTC timezone"
        print(f"✓ cancelled_at recorded in UTC: {cancelled_at}")
        
        # Validation 6: Amount preservation
        assert result['original_amount_usd'] == 50.00
        print("✓ Original amount preserved: $50.00")
        
        # Validation 7: Transaction management
        mock_conn.commit.assert_called_once()
        mock_conn.rollback.assert_not_called()
        print("✓ Transaction committed (no rollback)")
        
        # Validation 8: Database operations
        execute_calls = mock_cursor.execute.call_args_list
        assert len(execute_calls) >= 3, "Should have multiple database operations"
        print(f"✓ {len(execute_calls)} database operations executed")
        
        print("\n✅ Integration test passed! DoD verification:")
        print("   [✓] 實作了取消前的狀態機驗證邏輯")
        print("   [✓] 實作了完整的事務回滾機制")
        print("   [✓] 驗證 cancelled_at 已正確寫入當前時戳（UTC）")


def test_integration_state_machine_prevents_invalid_transitions():
    """
    Integration Test: State machine prevents invalid transitions
    
    Scenario:
    - Attempt to cancel completed booking
    - System should detect invalid state and reject
    - Should rollback without any database modifications
    """
    
    mock_booking = {
        'booking_id': 'BK-TRAVEL001',
        'user_id': 'RU02',
        'status': 'completed',
        'amount_usd': 75.00,
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
            booking_id='BK-TRAVEL001',
            reason='Customer request'
        )
        
        print("✓ State machine validation scenario: completed booking")
        
        # Validation 1: Rejection
        assert success is False, "Should reject completed booking"
        print("✓ Cancellation rejected")
        
        # Validation 2: Error message clarity
        assert 'completed' in result.lower(), "Error should mention the invalid state"
        assert 'cannot cancel' in result.lower(), "Error should explain why"
        print(f"✓ Error message descriptive: {result}")
        
        # Validation 3: No data modification
        mock_cursor.execute.assert_called_once()  # Only SELECT, no UPDATE
        update_calls = [call for call in mock_cursor.execute.call_args_list
                       if 'UPDATE' in str(call)]
        assert len(update_calls) == 0, "Should not execute UPDATE for invalid state"
        print("✓ No database modification for invalid state")
        
        # Validation 4: Transaction safety
        mock_conn.rollback.assert_called()
        mock_conn.commit.assert_not_called()
        print("✓ Transaction rolled back (prevent invalid state change)")
        
        print("\n✅ State machine test passed!")


def test_integration_audit_trail_timestamps():
    """
    Integration Test: Audit trail with proper UTC timestamps
    
    Scenario:
    - Cancel a confirmed booking
    - Verify cancelled_at timestamp is in UTC ISO format
    - Verify it can be parsed back to datetime
    - Verify it includes timezone info
    """
    
    mock_booking = {
        'booking_id': 'BK-CONFIRM001',
        'user_id': 'RU03',
        'status': 'confirmed',
        'amount_usd': 125.50,
        'booked_at': '2026-05-15T12:00:00+00:00'
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
        
        with patch('databases.relational.queries._gen_payment_id', return_value='PM-AUDIT001'):
            success, result = execute_cancellation(
                booking_id='BK-CONFIRM001',
                reason='Personal emergency'
            )
        
        print("✓ Audit trail recording scenario")
        
        assert success is True
        
        # Validation 1: Timestamp fields exist
        assert 'cancelled_at' in result
        assert 'cancellation_timestamp_utc' in result
        print("✓ Both cancelled_at and cancellation_timestamp_utc present")
        
        # Validation 2: Timestamp format
        cancelled_at = result['cancelled_at']
        timestamp_utc = result['cancellation_timestamp_utc']
        
        # Should match ISO 8601 format with UTC designation
        assert 'T' in cancelled_at, "Should be ISO format with T separator"
        assert '+00:00' in cancelled_at or 'Z' in cancelled_at, "Should indicate UTC"
        print(f"✓ cancelled_at is ISO 8601 UTC format: {cancelled_at}")
        
        # Validation 3: Timestamp parsing
        try:
            # Convert Z to +00:00 for parsing
            iso_string = cancelled_at.replace('Z', '+00:00')
            parsed_dt = datetime.fromisoformat(iso_string)
            
            # Verify it has timezone
            assert parsed_dt.tzinfo is not None, "Should have timezone info"
            
            # Verify it's recent (within last minute)
            now_utc = datetime.now(timezone.utc)
            time_diff = abs((now_utc - parsed_dt).total_seconds())
            assert time_diff < 60, "Timestamp should be recent"
            
            print(f"✓ Timestamp is valid and recent: {parsed_dt}")
        except ValueError as e:
            assert False, f"Cannot parse timestamp: {e}"
        
        # Validation 4: Audit data integrity
        assert result['cancellation_reason'] == 'Personal emergency'
        assert result['original_amount_usd'] == 125.50
        print("✓ All audit data preserved correctly")
        
        print("\n✅ Audit trail test passed!")


def test_integration_graceful_error_handling():
    """
    Integration Test: Graceful error handling with connection cleanup
    
    Scenario:
    - Database error occurs during cancellation
    - System should catch error, rollback transaction, and return error message
    - Connection should be properly closed
    """
    
    import psycopg2
    
    mock_booking = {
        'booking_id': 'BK-ERROR001',
        'user_id': 'RU04',
        'status': 'pending',
        'amount_usd': 40.00,
        'booked_at': '2026-05-18T16:00:00+00:00'
    }
    
    with patch('databases.relational.queries.psycopg2.connect') as mock_psycopg2_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        # First call (SELECT) succeeds, second call (UPDATE) fails
        mock_cursor.fetchone.return_value = mock_booking
        mock_cursor.execute.side_effect = [
            None,  # SELECT booking
            psycopg2.Error("Connection lost")  # UPDATE fails
        ]
        
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_psycopg2_connect.return_value = mock_conn
        
        success, result = execute_cancellation(
            booking_id='BK-ERROR001',
            reason='Test error'
        )
        
        print("✓ Error handling scenario: database failure")
        
        # Validation 1: Failure reported
        assert success is False, "Should report failure"
        assert isinstance(result, str), "Should return error message"
        print(f"✓ Error reported: {result}")
        
        # Validation 2: Rollback called
        mock_conn.rollback.assert_called()
        print("✓ Transaction rolled back")
        
        # Validation 3: Connection closed
        mock_conn.close.assert_called()
        print("✓ Database connection properly closed")
        
        # Validation 4: No commit
        mock_conn.commit.assert_not_called()
        print("✓ No partial commit (all-or-nothing)")
        
        print("\n✅ Error handling test passed!")


if __name__ == '__main__':
    test_integration_complete_cancellation_workflow()
    print("\n" + "="*60 + "\n")
    test_integration_state_machine_prevents_invalid_transitions()
    print("\n" + "="*60 + "\n")
    test_integration_audit_trail_timestamps()
    print("\n" + "="*60 + "\n")
    test_integration_graceful_error_handling()
    print("\n" + "="*60)
    print("✅ All integration tests passed!")
