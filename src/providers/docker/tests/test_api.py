import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from providers.docker.api import DockerCLI
from providers.docker.exceptions import DockerTransportError, DockerVMNotFoundError


def _process(*, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> SimpleNamespace:
    return SimpleNamespace(
        returncode=returncode,
        communicate=AsyncMock(return_value=(stdout, stderr)),
    )


@pytest.mark.asyncio
async def test_run_container_publishes_on_loopback_and_passes_env_via_file(monkeypatch):
    captured: dict = {}

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        # Read the env-file while it exists; run_container unlinks it afterwards.
        env_file = args[args.index("--env-file") + 1]
        captured["path"] = env_file
        captured["mode"] = os.stat(env_file).st_mode & 0o777
        with open(env_file, encoding="utf-8") as handle:
            captured["env_file"] = handle.read()
        return _process(stdout=b"container-id\n")

    monkeypatch.setattr("providers.docker.api.asyncio.create_subprocess_exec", fake_exec)

    container_id = await DockerCLI().run_container(
        name="sb-test",
        image="drukbox/sandbox:latest",
        env={"DRUKBOX_AUTHORIZED_KEY": "ssh-ed25519 KEY", "SECRET_TOKEN": "s3cr3t"},
        labels={"managed-by": "drukbox"},
    )

    assert container_id == "container-id"
    args = captured["args"]
    # Loopback publish + label still on argv; secrets are not.
    assert args[:8] == (
        "docker",
        "run",
        "--detach",
        "--name",
        "sb-test",
        "--publish",
        "127.0.0.1::22",
        "--label",
    )
    assert args[-1] == "drukbox/sandbox:latest"
    # Neither the secret value nor its name may appear in ANY argv token —
    # substring, not just standalone element — so a `-e KEY=val` / `--env=KEY=val`
    # regression that inlines a secret onto the command line fails here.
    assert all("s3cr3t" not in arg and "SECRET_TOKEN" not in arg for arg in args)
    assert not any(arg == "-e" or (arg.startswith("--env") and arg != "--env-file") for arg in args)
    # Env lives in the 0600 file (cleaned up after the run), not on the command line.
    assert "SECRET_TOKEN=s3cr3t" in captured["env_file"]
    assert "DRUKBOX_AUTHORIZED_KEY=ssh-ed25519 KEY" in captured["env_file"]
    assert captured["mode"] == 0o600
    assert not os.path.exists(captured["path"])


@pytest.mark.asyncio
async def test_run_container_rejects_newline_in_env(monkeypatch):
    create = AsyncMock(return_value=_process(stdout=b"id\n"))
    monkeypatch.setattr("providers.docker.api.asyncio.create_subprocess_exec", create)

    with pytest.raises(DockerTransportError, match="NUL or newline"):
        await DockerCLI().run_container(
            name="sb-test",
            image="img",
            env={"EVIL": "value\nINJECTED=x"},
            labels={},
        )
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_published_ssh_port_parses_loopback_binding(monkeypatch):
    create = AsyncMock(return_value=_process(stdout=b"127.0.0.1:49160\n"))
    monkeypatch.setattr("providers.docker.api.asyncio.create_subprocess_exec", create)

    assert await DockerCLI().published_ssh_port("sb-test") == 49160


@pytest.mark.asyncio
async def test_published_ssh_port_raises_when_container_published_nothing(monkeypatch):
    create = AsyncMock(return_value=_process(stdout=b"\n"))
    monkeypatch.setattr("providers.docker.api.asyncio.create_subprocess_exec", create)

    with pytest.raises(DockerTransportError):
        await DockerCLI().published_ssh_port("sb-test")


@pytest.mark.asyncio
async def test_missing_container_maps_to_not_found(monkeypatch):
    create = AsyncMock(
        return_value=_process(
            returncode=1,
            stderr=b"Error response from daemon: No such container: sb-test",
        )
    )
    monkeypatch.setattr("providers.docker.api.asyncio.create_subprocess_exec", create)

    with pytest.raises(DockerVMNotFoundError):
        await DockerCLI().remove_container("sb-test")


@pytest.mark.asyncio
async def test_other_failure_maps_to_transport_error(monkeypatch):
    create = AsyncMock(return_value=_process(returncode=1, stderr=b"Cannot connect to daemon"))
    monkeypatch.setattr("providers.docker.api.asyncio.create_subprocess_exec", create)

    with pytest.raises(DockerTransportError):
        await DockerCLI().server_version()


@pytest.mark.asyncio
async def test_missing_docker_binary_maps_to_transport_error(monkeypatch):
    create = AsyncMock(side_effect=FileNotFoundError("docker"))
    monkeypatch.setattr("providers.docker.api.asyncio.create_subprocess_exec", create)

    with pytest.raises(DockerTransportError):
        await DockerCLI().server_version()


@pytest.mark.asyncio
async def test_unstartable_docker_binary_maps_to_transport_error(monkeypatch):
    # A non-executable docker binary raises PermissionError (an OSError, not a
    # FileNotFoundError) at spawn; it must still be translated, not leak raw.
    create = AsyncMock(side_effect=PermissionError("docker"))
    monkeypatch.setattr("providers.docker.api.asyncio.create_subprocess_exec", create)

    with pytest.raises(DockerTransportError):
        await DockerCLI().server_version()


@pytest.mark.asyncio
async def test_run_container_cleans_up_env_file_when_docker_fails(monkeypatch):
    captured: dict = {}

    async def fake_exec(*args, **kwargs):
        captured["path"] = args[args.index("--env-file") + 1]
        return _process(returncode=1, stderr=b"boom")

    monkeypatch.setattr("providers.docker.api.asyncio.create_subprocess_exec", fake_exec)

    with pytest.raises(DockerTransportError):
        await DockerCLI().run_container(
            name="sb-test", image="img", env={"SECRET_TOKEN": "s3cr3t"}, labels={}
        )
    assert not os.path.exists(captured["path"])


@pytest.mark.asyncio
async def test_published_ssh_port_raises_on_unparsable_output(monkeypatch):
    create = AsyncMock(return_value=_process(stdout=b"127.0.0.1:notaport\n"))
    monkeypatch.setattr("providers.docker.api.asyncio.create_subprocess_exec", create)

    with pytest.raises(DockerTransportError, match="unparsable"):
        await DockerCLI().published_ssh_port("sb-test")
