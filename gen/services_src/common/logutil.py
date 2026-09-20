import logging
import time

from common.config import log_path


class UTCFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created))


def setup(service, level="INFO"):
    log = logging.getLogger(service)
    log.setLevel(getattr(logging, level.upper(), logging.INFO))
    log.propagate = False
    if not log.handlers:
        h = logging.FileHandler(log_path(service))
        h.setFormatter(UTCFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        log.addHandler(h)
    return log
