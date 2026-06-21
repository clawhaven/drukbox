import re
import shlex

_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def inject_env_exports(script: str, env: dict[str, str] | None) -> str:
    """Return ``script`` with ``env`` prepended as shell ``export`` lines.

    When the script starts with a shebang the exports go between the
    shebang and the body so the interpreter line stays first.

    Raises ``ValueError`` for env keys that aren't valid shell identifiers.
    """
    if not env:
        return script
    exports: list[str] = []
    for key, value in env.items():
        if not _ENV_NAME_RE.fullmatch(key):
            raise ValueError(f"invalid VM environment variable name: {key}")
        exports.append(f"export {key}={shlex.quote(value)}")
    if script.startswith("#!"):
        shebang, separator, body = script.partition("\n")
        if separator:
            return "\n".join([shebang, *exports, body])
        return "\n".join([shebang, *exports])
    return "\n".join([*exports, script])
