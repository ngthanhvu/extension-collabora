"""Small compatibility shim needed by pykakasi's legacy exports."""

import functools


def deprecated(*decorator_args, **decorator_kwargs):
    def decorate(function):
        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            return function(*args, **kwargs)
        return wrapped

    if decorator_args and callable(decorator_args[0]):
        return decorate(decorator_args[0])
    return decorate
