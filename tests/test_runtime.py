from dataclasses import replace

import pytest

from itov.config import initialize
from itov.runtime import launch_command


def test_local_runtime_uses_explicit_paths_without_assumed_acceleration(tmp_path):
    root = tmp_path / "portable with spaces"
    (root / "ComfyUI").mkdir(parents=True)
    (root / "ComfyUI/main.py").touch()
    (root / "python_embeded").mkdir()
    (root / "python_embeded/python.exe").touch()
    config = initialize(tmp_path / "work", root)
    command = launch_command(config)
    assert command[0] == str(root / "python_embeded/python.exe")
    assert command[command.index("--input-directory") + 1] == str(config.root / "input")
    assert "--disable-all-custom-nodes" in command and "--use-sage-attention" not in command
    assert "--disable-all-custom-nodes" not in launch_command(config, custom_nodes=True)


@pytest.mark.parametrize(
    "url",
    ["http://0.0.0.0:8188", "http://example.com", "https://localhost", "http://localhost/prefix"],
)
def test_remote_or_proxy_configuration_cannot_be_used_as_local_bind(tmp_path, url):
    config = initialize(tmp_path / "work", tmp_path / "absent")
    with pytest.raises(ValueError, match="loopback HTTP URL"):
        launch_command(replace(config, url=url))


def test_missing_runtime_cannot_launch(tmp_path):
    config = initialize(tmp_path / "work", tmp_path / "absent")
    with pytest.raises(ValueError, match="missing"):
        launch_command(config)
