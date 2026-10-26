"""Entry point of the Windows GUI executable (`outwarp-gui.exe`)."""
import contextlib
import os
import sys

from outwarp.app import main

code = main()
# main() has released the single-instance lock and shut the tunnel down. A
# non-daemon thread from a dependency (pystray's) must not keep the process
# alive after that: it would be a zombie with a tray icon and no lock, and the
# next launch would start a second instance.
for stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        stream.flush()
os._exit(code)
