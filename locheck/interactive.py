"""Reading a single keypress, when there is somebody there to press one.

The report has two audiences in the same person: the ship/no-ship glance, and
the detail needed to actually fix something. Printing both every time buries the
first in the second, so the details wait behind a keypress.

The whole feature is conditional on `someone_is_watching()`. A prompt that
appears in a CI log is a hang, not a feature: the build sits there until it times
out, with no indication why. So anything that is not a real terminal on both ends
gets the full report immediately and is never asked a question.
"""

from __future__ import annotations

import sys


def someone_is_watching() -> bool:
    """Whether there is a human at a terminal who could answer a prompt.

    Both ends have to be a terminal. Output redirected to a file means nobody
    will see the question; input redirected from one means nobody can answer it.
    A closed or detached stream raises rather than returning False on some
    platforms, hence the guard.
    """
    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return False
    except (AttributeError, ValueError):
        return False

    # On Windows that answer is not specific enough to act on. See below.
    if sys.platform == "win32":
        return _is_a_real_console(sys.stdin) and _is_a_real_console(sys.stdout)

    return True


def _is_a_real_console(stream) -> bool:
    """Whether a Windows stream is an actual console, not just a character device.

    `isatty()` on Windows means "is this a character device", and the NUL device
    is one. So `locheck ... > NUL` looked like a terminal to the guard above, the
    interactive path ran, and the tool sat on a keypress at a console the reader
    was not watching. `GetConsoleMode` succeeds only for a real console handle,
    which is the question the guard meant to ask all along.

    Anything unexpected here counts as "not a console": refusing to prompt costs
    a keypress, and prompting where nobody can answer costs the whole run.
    """
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        handle = msvcrt.get_osfhandle(stream.fileno())
        mode = wintypes.DWORD()
        return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
    except Exception:
        return False


def read_key() -> str:
    """Wait for one keypress and return it, without needing Enter.

    Returns "" if the key cannot be read - a detached stdin, an unsupported
    terminal - so the caller can carry on rather than fail. Ctrl-C and Ctrl-D
    raise KeyboardInterrupt, because a prompt that cannot be escaped is worse
    than no prompt.
    """
    try:
        import msvcrt  # Windows
    except ImportError:
        pass
    else:
        try:
            key = msvcrt.getwch()
        except Exception:
            return ""
        if key in ("\x03", "\x04"):
            raise KeyboardInterrupt
        return key

    try:
        import termios
        import tty
    except ImportError:
        return ""

    try:
        descriptor = sys.stdin.fileno()
        previous = termios.tcgetattr(descriptor)
    except Exception:
        return ""

    try:
        tty.setraw(descriptor)
        key = sys.stdin.read(1)
    except Exception:
        return ""
    finally:
        try:
            termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)
        except Exception:
            pass

    if key in ("\x03", "\x04"):
        raise KeyboardInterrupt
    return key
