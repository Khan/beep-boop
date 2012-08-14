import os


def relative_path(f):
    """Given f, which is assumed to be in the same directory as this util file,
    return the relative path to it."""
    return os.path.join(os.path.dirname(__file__), f)
