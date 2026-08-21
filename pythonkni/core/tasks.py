"""Framework-independent task primitives."""


class WorkerCancelled(Exception):
    """Control-flow exception used for cooperative task cancellation."""
