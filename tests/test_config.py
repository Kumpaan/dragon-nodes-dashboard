import pytest
import json
from pathlib import Path
from src.config import LocalConfigManager, CONFIG_DIR, CONFIG_FILE


# This decorator tells pytest that the test function is asynchronous and needs an event loop.
@pytest.mark.asyncio
async def test_local_config_manager_creates_file_and_saves_data(tmp_path: Path):
    """
    Test that LocalConfigManager correctly initializes its file structure in a sandbox
    and successfully executes asynchronous read/write operations.
    """
    # 1. ARRANGE: Set up the mock environment
    # tmp_path is a built-in pytest fixture that provides a unique temporary directory for this specific test run.
    manager = LocalConfigManager(base_dir=tmp_path)

    expected_config_path = tmp_path / CONFIG_DIR / CONFIG_FILE

    # Verify the initialization logic actually created the folders and empty JSON file.
    assert expected_config_path.exists()

    # 2. ACT: Execute the business logic
    mock_commands = [
        {"name": "Camera Fusion", "command": "ros2 run camera_fusion_node camera_fusion_node"},
        {"name": "SLAM", "command": "ros2 run slam_node slam_node"}
    ]
    await manager.save(mock_commands)

    # 3. ASSERT: Verify the outcome is unequivocally correct
    loaded_commands = await manager.load()

    assert loaded_commands == mock_commands
    assert len(loaded_commands) == 2
    assert loaded_commands[0]["name"] == "Camera Fusion"