import json
import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any
from typing import Literal
from typing import Mapping


repo_folder_path: Path = Path(__file__).parent
log_file_path: Path = repo_folder_path / "logs" / "app.log"


def create_logger(log_file_path: Path) -> logging.Logger:
    logger: logging.Logger = logging.getLogger(log_file_path.stem)

    if "pytest" in sys.modules:
        # when testing, use a logger that does nothing
        logger.addHandler(logging.NullHandler())
        return logger

    log_file_path.parent.mkdir(exist_ok=True, parents=True)

    # create a new log file every day using the local time zone and delete logs older than 14 days
    handler: TimedRotatingFileHandler = TimedRotatingFileHandler(
        filename=log_file_path,
        encoding="utf-8",
        utc=False,
        interval=1,
        when="D",
        backupCount=14,
    )

    fmt: str = os.environ.get("LOG_FORMAT", "JSON")
    assert fmt in ("JSON", "SIMPLE"), "Invalid LOG_FORMAT"
    datefmt: str = "%Y-%m-%d %H:%M:%S"
    match fmt:
        case "JSON":
            handler.setFormatter(JsonLogFormatter(datefmt))
        case "SIMPLE":
            handler.setFormatter(
                logging.Formatter("{asctime}[{levelname}]{message}", datefmt, style="{")
            )
        case _:
            raise ValueError('invalid LOG_FORMAT (valid options: "JSON", "SIMPLE")')

    logger.addHandler(handler)

    level: str = os.environ.get("LOG_LEVEL", "INFO")
    assert level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"), "Invalid LOG_LEVEL"
    logger.setLevel(level)

    return logger


class JsonLogFormatter(logging.Formatter):
    def __init__(
        self,
        datefmt: str | None = None,
        style: Literal["%", "{", "$"] = "%",
        validate: bool = True,
        /,
        defaults: Mapping[str, Any] | None = None,
    ):
        super().__init__(None, datefmt, style, validate, defaults=defaults)

    def format(self, record: logging.LogRecord) -> str:
        record_d: dict[str, Any] = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
        }
        message: str = record.getMessage()
        if message:
            record_d["message"] = message

        return json.dumps(record_d)


logger: logging.Logger = create_logger(log_file_path)
