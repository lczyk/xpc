import logging


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("server")
    handler = logging.StreamHandler()
    # format = "%(asctime)s %(levelname)s %(message)s"
    try:
        import colorlog

        handler.setFormatter(colorlog.ColoredFormatter("%(asctime)s %(log_color)s%(levelname)s%(reset)s %(message)s"))
    except ImportError:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    return logger
