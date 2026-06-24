import os
from pathlib import Path


def load_dotenv(path: str | Path = ".env", *, override: bool = False, env: dict | None = None) -> dict:
    target = os.environ if env is None else env
    dotenv = Path(path)
    if not dotenv.exists():
        return target
    for raw_line in dotenv.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or (not override and target.get(key)):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        target[key] = value
    return target
