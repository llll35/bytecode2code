"""Exception hierarchy for the multi-version support layer."""


class PyversError(Exception):
    """Base class for every error raised by :mod:`pyvers`."""


class UnsupportedVersionError(PyversError):
    """The .pyc magic number does not belong to any known CPython bytecode."""


class InterpreterNotFoundError(PyversError):
    """No interpreter is available to unmarshal the requested .pyc."""


class MarshalError(PyversError):
    """The .pyc payload could not be decoded by the selected interpreter."""


class WorkerError(PyversError):
    """The target interpreter ran but reported a failure."""

    def __init__(self, message, traceback_text=""):
        super().__init__(message)
        self.traceback_text = traceback_text
