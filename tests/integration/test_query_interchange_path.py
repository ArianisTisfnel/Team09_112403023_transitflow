"""
Integration test for query_interchange_path()
Tests cross-network interchange path queries with real Neo4j scenarios
(Mock-based integration test - simulates real database responses)
"""

from unittest.mock import MagicMock, patch
from databases.graph.queries import query_interchange_path


def test_interchange_path_metro_to_rail():
    """
    Scenario: User wants to travel from Metro Line 1 to National Rail
    Expected: Path crosses network boundary via INTERCHANGE relationship
    """
    
    # Mock data representing a metro → rail path
    mock_path = {
        "station_ids": ["MS01", "MS02", "MS03", "NR01", "NR02"],
        "stations": [
            {"station_id": "MS01", "name": "Central Metro", "network_type": "metro"},
            {"station_id": "MS02", "name": "Downtown Metro", "network_type": "metro"},
            {"station_id": "MS03", "name": "Junction Metro", "network_type": "metro"},
            {"station_id": "NR01", "name": "Junction Rail", "network_type": "national_rail"},
            {"station_id": "NR02", "name": "Central Rail", "network_type": "national_rail"},
        ],
        "travel_times": [3, 2, 1, 5],
    }
    
    mock_relationships = [
        {
            "from_id": "MS01", "from_name": "Central Metro", "from_network": "metro",
            "to_id": "MS02", "to_name": "Downtown Metro", "to_network": "metro",
            "rel_type": "CONNECTS_TO", "travel_time": 3,
        },
        {
            "from_id": "MS02", "from_name": "Downtown Metro", "from_network": "metro",
            "to_id": "MS03", "to_name": "Junction Metro", "to_network": "metro",
            "rel_type": "CONNECTS_TO", "travel_time": 2,
        },
        {
            "from_id": "MS03", "from_name": "Junction Metro", "from_network": "metro",
            "to_id": "NR01", "to_name": "Junction Rail", "to_network": "national_rail",
            "rel_type": "INTERCHANGE", "travel_time": 1,
        },
        {
            "from_id": "NR01", "from_name": "Junction Rail", "from_network": "national_rail",
            "to_id": "NR02", "to_name": "Central Rail", "to_network": "national_rail",
            "rel_type": "CONNECTS_TO", "travel_time": 5,
        },
    ]
    
    with patch('databases.graph.queries.get_pool') as mock_get_pool:
        mock_driver = MagicMock()
        mock_session = MagicMock()

        mock_get_pool.return_value.__enter__.return_value = mock_driver
        mock_driver.session.return_value.__enter__.return_value = mock_session
        
        mock_result_1 = MagicMock()
        mock_result_1.single.return_value = mock_path
        
        mock_result_2 = MagicMock()
        mock_result_2.fetch.return_value = mock_relationships
        
        mock_session.run.side_effect = [mock_result_1, mock_result_2]
        
        # Test
        result = query_interchange_path("MS01", "NR02")
        
        # Verify result structure
        assert result["found"] is True
        assert result["origin_id"] == "MS01"
        assert result["destination_id"] == "NR02"
        assert result["station_ids"] == ["MS01", "MS02", "MS03", "NR01", "NR02"]
        assert result["total_travel_time_min"] == 11
        assert result["num_legs"] == 4
        
        # Verify interchange point is explicitly marked
        assert len(result["interchange_points"]) == 1
        interchange = result["interchange_points"][0]
        assert interchange["from_station_id"] == "MS03"
        assert interchange["to_station_id"] == "NR01"
        assert interchange["from_network"] == "metro"
        assert interchange["to_network"] == "national_rail"
        
        # Verify legs include all transitions
        assert len(result["legs"]) == 4
        
        # Verify the interchange relationship type is marked
        interchange_leg = None
        for leg in result["legs"]:
            if leg["from_station_id"] == "MS03" and leg["to_station_id"] == "NR01":
                interchange_leg = leg
                break
        
        assert interchange_leg is not None
        assert interchange_leg["relationship_type"] == "INTERCHANGE"
        
        print("✓ Test passed: Metro → Rail interchange path")


def test_interchange_path_rail_to_metro():
    """
    Scenario: User wants to travel from National Rail to Metro Line
    Expected: Path crosses network boundary via INTERCHANGE relationship
    """
    
    mock_path = {
        "station_ids": ["NR05", "NR04", "MS05", "MS06"],
        "stations": [
            {"station_id": "NR05", "name": "North Rail", "network_type": "national_rail"},
            {"station_id": "NR04", "name": "Station Rail", "network_type": "national_rail"},
            {"station_id": "MS05", "name": "Station Metro", "network_type": "metro"},
            {"station_id": "MS06", "name": "South Metro", "network_type": "metro"},
        ],
        "travel_times": [4, 1, 2],
    }
    
    mock_relationships = [
        {
            "from_id": "NR05", "from_name": "North Rail", "from_network": "national_rail",
            "to_id": "NR04", "to_name": "Station Rail", "to_network": "national_rail",
            "rel_type": "CONNECTS_TO", "travel_time": 4,
        },
        {
            "from_id": "NR04", "from_name": "Station Rail", "from_network": "national_rail",
            "to_id": "MS05", "to_name": "Station Metro", "to_network": "metro",
            "rel_type": "INTERCHANGE", "travel_time": 1,
        },
        {
            "from_id": "MS05", "from_name": "Station Metro", "from_network": "metro",
            "to_id": "MS06", "to_name": "South Metro", "to_network": "metro",
            "rel_type": "CONNECTS_TO", "travel_time": 2,
        },
    ]
    
    with patch('databases.graph.queries.get_pool') as mock_get_pool:
        mock_driver = MagicMock()
        mock_session = MagicMock()

        mock_get_pool.return_value.__enter__.return_value = mock_driver
        mock_driver.session.return_value.__enter__.return_value = mock_session
        
        mock_result_1 = MagicMock()
        mock_result_1.single.return_value = mock_path
        
        mock_result_2 = MagicMock()
        mock_result_2.fetch.return_value = mock_relationships
        
        mock_session.run.side_effect = [mock_result_1, mock_result_2]
        
        # Test
        result = query_interchange_path("NR05", "MS06")
        
        # Verify interchange point
        assert result["found"] is True
        assert len(result["interchange_points"]) == 1
        interchange = result["interchange_points"][0]
        assert interchange["from_station_id"] == "NR04"
        assert interchange["to_station_id"] == "MS05"
        assert interchange["from_network"] == "national_rail"
        assert interchange["to_network"] == "metro"
        
        print("✓ Test passed: Rail → Metro interchange path")


def test_interchange_path_multiple_interchanges():
    """
    Scenario: Complex path with multiple INTERCHANGE points
    Expected: All interchange points are explicitly identified
    """
    
    mock_path = {
        "station_ids": ["MS01", "NR01", "MS02", "NR02"],
        "stations": [
            {"station_id": "MS01", "name": "Metro 1", "network_type": "metro"},
            {"station_id": "NR01", "name": "Rail 1", "network_type": "national_rail"},
            {"station_id": "MS02", "name": "Metro 2", "network_type": "metro"},
            {"station_id": "NR02", "name": "Rail 2", "network_type": "national_rail"},
        ],
        "travel_times": [1, 1, 1],
    }
    
    mock_relationships = [
        {
            "from_id": "MS01", "from_name": "Metro 1", "from_network": "metro",
            "to_id": "NR01", "to_name": "Rail 1", "to_network": "national_rail",
            "rel_type": "INTERCHANGE", "travel_time": 1,
        },
        {
            "from_id": "NR01", "from_name": "Rail 1", "from_network": "national_rail",
            "to_id": "MS02", "to_name": "Metro 2", "to_network": "metro",
            "rel_type": "INTERCHANGE", "travel_time": 1,
        },
        {
            "from_id": "MS02", "from_name": "Metro 2", "from_network": "metro",
            "to_id": "NR02", "to_name": "Rail 2", "to_network": "national_rail",
            "rel_type": "INTERCHANGE", "travel_time": 1,
        },
    ]
    
    with patch('databases.graph.queries.get_pool') as mock_get_pool:
        mock_driver = MagicMock()
        mock_session = MagicMock()

        mock_get_pool.return_value.__enter__.return_value = mock_driver
        mock_driver.session.return_value.__enter__.return_value = mock_session
        
        mock_result_1 = MagicMock()
        mock_result_1.single.return_value = mock_path
        
        mock_result_2 = MagicMock()
        mock_result_2.fetch.return_value = mock_relationships
        
        mock_session.run.side_effect = [mock_result_1, mock_result_2]
        
        # Test
        result = query_interchange_path("MS01", "NR02")
        
        # Verify all interchange points are identified
        assert result["found"] is True
        assert len(result["interchange_points"]) == 3
        
        # Verify each interchange point
        assert result["interchange_points"][0]["from_station_id"] == "MS01"
        assert result["interchange_points"][0]["to_station_id"] == "NR01"
        
        assert result["interchange_points"][1]["from_station_id"] == "NR01"
        assert result["interchange_points"][1]["to_station_id"] == "MS02"
        
        assert result["interchange_points"][2]["from_station_id"] == "MS02"
        assert result["interchange_points"][2]["to_station_id"] == "NR02"
        
        print("✓ Test passed: Multiple interchange points path")


if __name__ == "__main__":
    test_interchange_path_metro_to_rail()
    test_interchange_path_rail_to_metro()
    test_interchange_path_multiple_interchanges()
    print("\n✓ All integration tests passed")
