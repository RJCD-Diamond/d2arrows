import re

_PATTERN = re.compile(r"^([a-zA-Z]+)(\d+)-(\d+)$")


def split_instrument_session(instrument_session: str) -> tuple[str, int, int]:
    """
    Split instrument_session like:
        cm12345-1
        cy45322-2
        mx93438-5

    Returns:
        (prefix, id_number, suffix_number)

    Raises:
        ValueError if the format is invalid.
    """
    match = _PATTERN.fullmatch(instrument_session.strip())
    if not match:
        raise ValueError(
            f"Invalid format: {instrument_session!r} - must be like: cm12345-1"
        )

    prosal_code, proposal_number, visit_number = match.groups()
    return prosal_code, int(proposal_number), int(visit_number)
