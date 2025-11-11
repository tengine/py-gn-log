from importlib.metadata import files
import logging
import logging.handlers
import os
import sys

from . import json_formatter
from . import level

# https://docs.python.org/3/library/logging.html#formatter-objects
LOCAL_LOG_FORMAT = '%(asctime)s %(levelname)s pid:%(process)s %(message)s:%(filename)s:%(lineno)d'

class Initializer:
    def __init__(self, log_level: int | None = None, output_path: str | None = None, log_format: str | None = None):
        print("Initializer starting", file=sys.stderr)
        # print_loggers("at the start of Initializer.__init__")

        handler: logging.Handler
        if os.getenv("K_SERVICE") is not None:
            handler = logging.StreamHandler(sys.stdout)  # または sys.stderr
            handler.setFormatter(json_formatter.JsonFormatter())
        else:
            if output_path is None:
                output_path = os.getenv('LOG_FILE_PATH')
            if output_path is None:
                handler = logging.StreamHandler(sys.stdout)  # または sys.stderr
            else:
                handler = logging.handlers.RotatingFileHandler(output_path, maxBytes=1024 * 1024 * 5, backupCount=5, encoding = 'utf-8')

            if log_format is None:
                log_format = os.getenv('LOG_FORMAT', LOCAL_LOG_FORMAT)
            handler.setFormatter(logging.Formatter(log_format))

        if log_level is None:
            log_level = level.from_env()
        handler.setLevel(log_level)
        self.handler = handler
        self.log_level_default = log_level

        if logging.root.hasHandlers():
            print(f"clearing handlers of logging.root: {logging.root.handlers}", file=sys.stderr)
            logging.root.handlers.clear()
        logging.root.addHandler(handler)

        # print_loggers("at the end of Initializer.__init__")


    def apply(self, name: str, log_level: int | None = None, propagate: bool | None = None, clear_handlers: bool = False, add_handler: bool = False) -> logging.Logger:
        logger = logging.getLogger(name)
        if log_level is None:
            log_level = self.log_level_default
        logger.setLevel(log_level)
        if propagate is not None:
            logger.propagate = propagate
        if clear_handlers:
            if logger.hasHandlers():
                print(f"clearing handlers of logger {logger.name}: {logger.handlers}", file=sys.stderr)
                logger.handlers.clear()
        if add_handler:
            logger.addHandler(self.handler)
        _print_logger(logger, "Initializer initialized logger")
        return logger

def print_loggers(prefix: str) -> None:
    _print_logger(logging.root, prefix)
    _print_loggers(logging.root, prefix)

def _print_loggers(parent: logging.Logger, prefix: str) -> None:
    for logger in parent.getChildren():
        _print_logger(logger, prefix)
        _print_loggers(logger, prefix)

def _print_logger(logger: logging.Logger, prefix: str) -> None:
    print(f"{prefix}\t{logger.name=}\tlogger.parent={logger.parent.name if logger.parent else 'no_parent'}\t{logger.propagate=}\tlen(logger.getChildren())={len(logger.getChildren())}\tlen(logger.handlers)={len(logger.handlers)}\t{logger.handlers=}", file=sys.stderr)
