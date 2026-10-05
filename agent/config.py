import tomllib
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
REPO_DIR = AGENT_DIR.parent
EXAMPLE = AGENT_DIR / "config.example.toml"


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(path: Path | None = None) -> dict:
    """Налаштування за замовчуванням із config.example.toml + твої зміни з config.toml.

    Так нові опції з оновлень працюють одразу, а config.toml правити не треба.
    """
    with open(EXAMPLE, "rb") as f:
        cfg = tomllib.load(f)
    path = path or AGENT_DIR / "config.toml"
    if path.exists() and path != EXAMPLE:
        with open(path, "rb") as f:
            cfg = _merge(cfg, tomllib.load(f))
    return cfg
