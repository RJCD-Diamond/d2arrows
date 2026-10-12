from tiled.client import from_uri

TILED_URL = "https://tiled.diamond.ac.uk"


TILED_STALE_TIME = 60 * 15

tiled_client = from_uri(uri=TILED_URL)
