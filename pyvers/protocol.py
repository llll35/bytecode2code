"""Wire format between the host process and the target interpreter worker."""

import json

BEGIN_MARK = "@@PYVERS-JSON-BEGIN@@"
END_MARK = "@@PYVERS-JSON-END@@"


def encode(payload):
    """Serialise *payload* into a marked block that survives noisy stdout."""
    body = json.dumps(payload, ensure_ascii=False)
    return "%s\n%s\n%s\n" % (BEGIN_MARK, body, END_MARK)


def extract(text):
    """Pull the JSON body out of a worker transcript.

    Raises :class:`ValueError` when the markers are missing, which means the
    worker died before it could answer.
    """
    if not text:
        raise ValueError("worker produced no output")
    start = text.rfind(BEGIN_MARK)
    if start < 0:
        raise ValueError("worker output did not contain a response block")
    start += len(BEGIN_MARK)
    end = text.find(END_MARK, start)
    if end < 0:
        raise ValueError("worker response block was truncated")
    return json.loads(text[start:end].strip())


def request(op, **fields):
    payload = {"op": op}
    payload.update(fields)
    return payload
