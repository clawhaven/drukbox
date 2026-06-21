from pathlib import Path


def test_host_lifecycle_does_not_use_blocking_subprocess_or_sync_http_clients():
    src_root = Path(__file__).resolve().parents[2]
    source_paths = [
        src_root / "hosts" / "service.py",
        src_root / "providers" / "exe" / "api.py",
        src_root / "networking" / "tailscale.py",
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in source_paths)

    assert "subprocess.run" not in source
    assert "subprocess.Popen" not in source
    assert "requests." not in source
    assert "httpx.Client" not in source


def test_service_source_does_not_import_django():
    src_root = Path(__file__).resolve().parents[2]
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in src_root.rglob("*.py")
        if "__pycache__" not in path.parts
        if "tests" not in path.parts
    )

    assert "import django" not in source
    assert "from django" not in source
