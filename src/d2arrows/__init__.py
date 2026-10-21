"""Top level API.

.. data:: __version__
    :type: str

    Version number as calculated by https://github.com/pypa/setuptools_scm
"""

import logging

from d2arrows._version import __version__

__all__ = ["__version__"]

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(asctime)s %(name)s: %(message)s",
    datefmt="%H:%M:%S %d-%m-%Y",
)
logger = logging.getLogger(__name__)

# httpx logs every request at INFO, which floods the output when using tiled
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
