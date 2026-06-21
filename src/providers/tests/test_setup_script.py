import pytest

from providers.setup_script import inject_env_exports


def test_returns_script_unchanged_when_no_env():
    script = "#!/usr/bin/env bash\necho hi\n"
    assert inject_env_exports(script, env=None) == script
    assert inject_env_exports(script, env={}) == script


def test_prepends_exports_after_shebang():
    script = "#!/usr/bin/env bash\nset -e\necho ready\n"
    out = inject_env_exports(script, env={"FOO": "bar", "QUOTE": "a b c"})
    # Shebang stays on the first line; exports follow before the body.
    shebang_idx = out.index("#!/usr/bin/env bash")
    export_idx = out.index("export FOO=bar")
    body_idx = out.index("set -e")
    assert shebang_idx < export_idx < body_idx
    # shell-quoted values guard against weird chars.
    assert "export QUOTE='a b c'" in out


def test_prepends_exports_to_non_shebanged_script():
    out = inject_env_exports("echo hi", env={"FOO": "bar"})
    assert out == "export FOO=bar\necho hi"


def test_rejects_invalid_env_names():
    with pytest.raises(ValueError, match="invalid VM environment variable name"):
        inject_env_exports("echo hi", env={"BAD-NAME": "v"})
