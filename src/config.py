import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click  # https://click.palletsprojects.com/en/stable/


# All path config variables must be of type `Path`, not `Path | None`, so that they can be
# correctly loaded from JSON.


@dataclass
class Config:
    """Saves user input for easy reuse"""

    ssh_host: str | None = None
    remote_parent_folder: Path = Path().home() / "repos"
    remote_port: int | None = None
    proxy_ip_address: str | None = None

    _path: Path = Path(click.get_app_dir("deploy")) / "config.json"
    _path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> None:
        try:
            new_config: Any = json.loads(self._path.read_text(encoding="utf8", errors="ignore"))
        except (FileNotFoundError, json.JSONDecodeError):
            return

        if isinstance(new_config, dict):
            for k, new_v in new_config.items():
                try:
                    old_v: Any = getattr(self, k)
                    if isinstance(old_v, Path):
                        setattr(self, k, Path(new_v))
                    else:
                        setattr(self, k, new_v)
                except AttributeError:
                    pass

    def save(self) -> None:
        # turn the config into a JSON-serializable dictionary
        config_d: dict[str, Any] = dict()
        for k, v in vars(self).items():
            if k.startswith("_"):
                continue
            elif isinstance(v, Path):
                config_d[k] = str(v)
            else:
                config_d[k] = v

        self._path.write_text(json.dumps(config_d), encoding="utf8")
