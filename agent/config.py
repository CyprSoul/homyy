import tomllib
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
REPO_DIR = AGENT_DIR.parent


def load_config(path: Path | None = None) -> dict:
    path = path or AGENT_DIR / "config.toml"
    if not path.exists():
        path = AGENT_DIR / "config.example.toml"
    with open(path, "rb") as f:
        return tomllib.load(f)
