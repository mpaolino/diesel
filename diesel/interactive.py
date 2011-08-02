"""An interactive interpreter inside of a diesel event loop.

It's useful for importing and interacting with code that expects to run
inside of a diesel event loop. It works especially well for interactive
sessions with diesel's various network protocol clients.

Supports both the standard Python interactive interpreter and IPython (if
installed).

"""
import code
import sys

import diesel

try:
    from IPython.Shell import IPShell
    IPYTHON_AVAILABLE = True
except ImportError:
    IPYTHON_AVAILABLE = False


# Library Functions:
# ==================

def interact_python():
    """Runs an interactive interpreter; halts the diesel app when finished."""
    globals_ = globals()
    env = {
        '__builtins__':globals_['__builtins__'],
        '__doc__':globals_['__doc__'],
        '__name__':globals_['__name__'],
        'diesel':diesel,
    }
    code.interact(None, None, env)
    diesel.quickstop()

def interact_ipython():
    """Starts an IPython instance; halts the diesel app when finished."""
    IPShell(user_ns={'diesel':diesel}).mainloop()
    diesel.quickstop()

# Interpreter entry points:
# =========================

def python():
    diesel.quickstart(interact_python)

def ipython():
    if not IPYTHON_AVAILABLE:
        print >> sys.stderr, "IPython not found."
        raise SystemExit(1)
    diesel.quickstart(interact_ipython)

