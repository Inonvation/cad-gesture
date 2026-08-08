"""日志模块 - 文件 + 控制台双写"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_logger = None


def get_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger

    logger = logging.getLogger("cad_gesture")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    fmt = logging.Formatter(
        "[Gesture] %(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        tmp = os.environ.get("TEMP", os.path.expanduser("~"))
        log_path = os.path.join(tmp, "cad-gesture.log")
        fh = RotatingFileHandler(
            log_path, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass

    try:
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(logging.INFO)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    except Exception:
        pass

    _logger = logger
    return logger
