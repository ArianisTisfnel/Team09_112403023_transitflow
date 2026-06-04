"""
Test for query_interchange_path()
Tests cross-network interchange path queries with INTERCHANGE relationship requirement
"""

from unittest.mock import Mock, MagicMock, patch
from databases.graph.queries import query_interchange_path


def test_query_interchange_path_found():
    """Test: interchange path exists between metro and national rail stations"""

    mock_station_ids = ["MS03", "MS04", "NR05", "NR06"]
    mock_stations = [
        {"station_id": "MS03", "name": "Metro Station 3", "network_type": "metro"},
        {"station_id": "MS04", "name": "Metro Station 4", "network_type": "metro"},
        {"station_id": "NR05", "name": "National Rail 5", "network_type": "national_rail"},
        {"station_id": "NR06", "name": "National Rail 6", "network_type": "national_rail"},
    ]

    with patch('databases.graph.queries.get_pool') as mock_get_pool:
        # Setup mock pool and session (get_pool() used as context manager)
        mock_driver = MagicMock()
        mock_session = MagicMock()

        mock_get_pool.return_value.__enter__.return_value = mock_driver
        mock_driver.session.return_value.__enter__.return_value = mock_session
        
        # Mock first query result (path finding with INTERCHANGE)
        mock_result_1 = MagicMock()
        mock_record_1 = {
            "station_ids": mock_station_ids,
            "stations": mock_stations,
            "travel_times": [2, 1, 3],
        }
        mock_result_1.single.return_value = mock_record_1
        
        # Mock second query result (relationship details)
        mock_result_2 = MagicMock()
        mock_rel_records = [
            {
                "from_id": "MS03",
                "from_name": "Metro Station 3",
                "from_network": "metro",
                "to_id": "MS04",
                "to_name": "Metro Station 4",
                "to_network": "metro",
                "rel_type": "CONNECTS_TO",
                "travel_time": 2,
            },
            {
                "from_id": "MS04",
                "from_name": "Metro Station 4",
                "from_network": "metro",
                "to_id": "NR05",
                "to_name": "National Rail 5",
                "to_network": "national_rail",
                "rel_type": "INTERCHANGE",
                "travel_time": 1,
            },
            {
                "from_id": "NR05",
                "from_name": "National Rail 5",
                "from_network": "national_rail",
                "to_id": "NR06",
                "to_name": "National Rail 6",
                "to_network": "national_rail",
                "rel_type": "CONNECTS_TO",
                "travel_time": 3,
            },
        ]
        mock_result_2.fetch.return_value = mock_rel_records
        
        # Configure mock session to return different results for different queries
        mock_session.run.side_effect = [mock_result_1, mock_result_2]
        
        # Call function
        result = query_interchange_path("MS03", "NR06")
        
        # Assertions
        assert result["found"] is True
        assert result["origin_id"] == "MS03"
        assert result["destination_id"] == "NR06"
        assert result["station_ids"] == mock_station_ids
        assert result["total_travel_time_min"] == 6  # 2 + 1 + 3
        assert len(result["legs"]) == 3
        
        # Verify interchange point is identified
        assert len(result["interchange_points"]) == 1
        interchange = result["interchange_points"][0]
        assert interchange["from_station_id"] == "MS04"
        assert interchange["from_network"] == "metro"
        assert interchange["to_station_id"] == "NR05"
        assert interchange["to_network"] == "national_rail"
        
        print("✓ Test passed: interchange path found")


def test_query_interchange_path_not_found():
    """Test: no interchange path exists between two stations"""

    with patch('databases.graph.queries.get_pool') as mock_get_pool:
        # Setup mock pool and session (get_pool() used as context manager)
        mock_driver = MagicMock()
        mock_session = MagicMock()

        mock_get_pool.return_value.__enter__.return_value = mock_driver
        mock_driver.session.return_value.__enter__.return_value = mock_session
        
        # Mock result with no path found
        mock_result = MagicMock()
        mock_result.single.return_value = None
        
        mock_session.run.return_value = mock_result
        
        # Call function
        result = query_interchange_path("MS01", "MS10")
        
        # Assertions
        assert result["found"] is False
        assert result["origin_id"] == "MS01"
        assert result["destination_id"] == "MS10"
        assert result["station_ids"] == []
        assert result["interchange_points"] == []
        assert "No interchange path found" in result["error"]
        
        print("✓ Test passed: no interchange path found")


def test_query_interchange_path_error():
    """Test: query execution error handling"""

    with patch('databases.graph.queries.get_pool') as mock_get_pool:
        # Setup mock to raise an exception on pool context manager entry
        mock_get_pool.return_value.__enter__.side_effect = Exception("Connection failed")
        
        # Call function
        result = query_interchange_path("MS03", "NR05")
        
        # Assertions
        assert result["found"] is False
        assert "error" in result
        assert "Connection failed" in result["error"]
        
        print("✓ Test passed: error handling")


if __name__ == "__main__":
    test_query_interchange_path_found()
    test_query_interchange_path_not_found()
    test_query_interchange_path_error()
    print("\n✓ All tests passed")
