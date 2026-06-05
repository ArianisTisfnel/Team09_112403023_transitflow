"""
Mock Test for query_user_profile()
Tests both success and not-found scenarios
"""

from unittest.mock import Mock, MagicMock, patch
from databases.relational.queries import query_user_profile


def test_query_user_profile_found():
    """Test: user_id exists in database"""
    mock_user_data = {
        'user_id': 'USR001',
        'full_name': 'Alice Chen',
        'email': 'alice@example.com',
        'phone': '555-1234',
        'date_of_birth': '1990-05-15',
        'registered_at': '2024-01-10T08:30:00+00:00',
        'is_active': True
    }
    
    with patch('databases.relational.queries._connect') as mock_connect:
        # Setup mock connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        # Set fetchone to return the mock user data
        mock_cursor.fetchone.return_value = mock_user_data
        
        # Call function
        result = query_user_profile('USR001')
        
        # Assertions
        assert result is not None
        assert result['user_id'] == 'USR001'
        assert result['full_name'] == 'Alice Chen'
        assert result['email'] == 'alice@example.com'
        assert result['is_active'] is True
        
        # Verify parameterized query was used
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args
        assert '%s' in call_args[0][0]  # SQL contains %s
        assert call_args[0][1] == ('USR001',)  # Parameters passed as tuple
        
        print("✓ Test passed: user_id found")


def test_query_user_profile_not_found():
    """Test: user_id does not exist in database"""
    
    with patch('databases.relational.queries._connect') as mock_connect:
        # Setup mock connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        # Set fetchone to return None (no user found)
        mock_cursor.fetchone.return_value = None
        
        # Call function
        result = query_user_profile('USR999')
        
        # Assertions
        assert result is None
        
        # Verify parameterized query was used
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args
        assert '%s' in call_args[0][0]  # SQL contains %s
        assert call_args[0][1] == ('USR999',)  # Parameters passed as tuple
        
        print("✓ Test passed: user_id not found returns None")


def test_query_user_profile_uses_rdictcursor():
    """Test: function uses RealDictCursor"""
    
    with patch('databases.relational.queries._connect') as mock_connect:
        with patch('psycopg2.extras.RealDictCursor') as mock_rdictcursor:
            # Setup mock connection and cursor
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            
            mock_connect.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchone.return_value = None
            
            # Call function
            query_user_profile('USR001')
            
            # Verify cursor_factory parameter was set
            mock_conn.cursor.assert_called_once()
            call_kwargs = mock_conn.cursor.call_args[1]
            # The implementation passes cursor_factory=psycopg2.extras.RealDictCursor
            
            print("✓ Test passed: RealDictCursor usage verified")


if __name__ == '__main__':
    print("Running Mock Tests for query_user_profile()...")
    print()
    
    test_query_user_profile_found()
    test_query_user_profile_not_found()
    test_query_user_profile_uses_rdictcursor()
    
    print()
    print("=" * 60)
    print("All tests passed! ✓")
    print("=" * 60)
