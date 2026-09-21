from pathlib import Path

import pytest

from itov.config import DIRECTORIES, initialize, load_config, validate_url


def test_initialization_keeps_existing_files_and_resolves_from_config(tmp_path, monkeypatch):
    root = tmp_path / "workspace with spaces"
    (root / "input").mkdir(parents=True)
    image = root / "input" / "keep.png"
    image.write_bytes(b"original image")
    portable = tmp_path / "portable"
    (portable / "ComfyUI").mkdir(parents=True)
    (portable / "ComfyUI" / "main.py").touch()
    (portable / "python_embeded").mkdir()
    python = portable / "python_embeded" / "python.exe"
    python.touch()
    config = initialize(root, portable)
    monkeypatch.chdir(tmp_path.parent)
    loaded = load_config(config.file)
    assert loaded.comfyui_root == portable / "ComfyUI"
    assert loaded.python == python
    assert all((root / name).is_dir() for name in DIRECTORIES)
    assert image.read_bytes() == b"original image"


def test_init_refuses_config_overwrite(tmp_path):
    config = initialize(tmp_path / "work", tmp_path / "comfy")
    before = config.file.read_bytes()
    with pytest.raises(FileExistsError):
        initialize(config.root, tmp_path / "different")
    assert config.file.read_bytes() == before


def test_init_rejects_occupied_directory_before_creating_config(tmp_path):
    (tmp_path / "state").write_text("keep this")
    with pytest.raises(ValueError, match="occupied"):
        initialize(tmp_path, tmp_path / "comfy")
    assert not (tmp_path / "itov.toml").exists()
    assert not (tmp_path / "input").exists()
    assert (tmp_path / "state").read_text() == "keep this"


@pytest.mark.parametrize(
    "value",
    [
        "ftp://localhost",
        "http://user:password@localhost",
        "http://localhost?x=1",
        "http://localhost:0",
        "http://localhost:99999",
        "http://local host",
        "",
    ],
)
def test_bad_urls_are_rejected(value):
    with pytest.raises(ValueError):
        validate_url(value)


@pytest.mark.parametrize(
    "text",
    [
        "version = 2",
        "version = true",
        "version = 1\n[comfyui]\nroot = true\nurl = 'http://localhost'",
        "version = 1\n[comfyui]\nroot = '.'\nurl = 'http://localhost'\nunknown = 1",
    ],
)
def test_invalid_config_is_rejected(tmp_path, text):
    config = tmp_path / "itov.toml"
    config.write_text(text)
    with pytest.raises(ValueError):
        load_config(config)


def test_explicit_interpreter_survives_load(tmp_path):
    python = tmp_path / "manual" / "python.exe"
    config = initialize(tmp_path / "work", tmp_path / "comfy", python=python)
    assert config.python == python
    assert not Path(config.file.read_text().split('root = "')[1].split('"')[0]).is_absolute()
