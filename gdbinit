# neo-mittens gdb config
# Generic settings for all projects

# Allow loading .gdbinit from any directory
set auto-load safe-path /

# Disable pagination (prevents "press enter to continue")
set pagination off

# Enable debuginfod without prompt
set debuginfod enabled on

# Pretty printing
set print pretty on
set print array on
set print array-indexes on

# Better history
set history save on
set history size 10000
set history filename ~/.gdb_history

# Don't stop on thread signals
handle SIGUSR1 nostop noprint
handle SIGUSR2 nostop noprint

# Shortcuts
define loc
  info locals
end

define args
  info args
end

define bt5
  backtrace 5
end

define threads
  info threads
end

# Toggle breakpoint at location (usage: tb file:line)
python
class ToggleBreakpoint(gdb.Command):
    """Toggle breakpoint at location: tb file:line"""
    def __init__(self):
        super().__init__("tb", gdb.COMMAND_BREAKPOINTS)

    def invoke(self, arg, from_tty):
        loc = arg.strip()
        if not loc:
            print("Usage: tb file:line")
            return
        # Check if breakpoint exists at this location
        found = False
        for bp in gdb.breakpoints() or []:
            if bp.location == loc:
                bp.delete()
                print(f"Deleted breakpoint at {loc}")
                found = True
                break
        if not found:
            gdb.execute(f"break {loc}")

ToggleBreakpoint()
end

# Jump to current location in nvim
define v
  python
import subprocess
import os
nvim_sock = os.environ.get('NVIM_SOCK', '/tmp/nvim.sock')
frame = gdb.selected_frame()
sal = frame.find_sal()
if sal.symtab:
    filename = sal.symtab.fullname()
    line = sal.line
    subprocess.run(['nvim', '--server', nvim_sock, '--remote-send', f'<Esc>:e +{line} {filename}<CR>'],
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
else:
    print("No source info available")
  end
end

# Nvim integration - push state on events
python
import subprocess
import os
import json

def get_nvim_sock():
    """Get nvim socket path based on cwd (matches nvim's logic)"""
    if os.environ.get('NVIM_SOCK'):
        return os.environ['NVIM_SOCK']
    cwd = os.getcwd()
    project = os.path.basename(cwd)
    return f'/tmp/nvim-{project}.sock'

import socket
import struct

def send_to_nvim(lua_code):
    """Send lua command to nvim via msgpack-rpc socket (no subprocess)"""
    nvim_sock = get_nvim_sock()
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(nvim_sock)
        # msgpack-rpc notification: [2, method, args]
        # method = "nvim_exec_lua", args = [lua_code, {}]
        import msgpack
        msg = msgpack.packb([2, "nvim_exec_lua", [lua_code, []]])
        sock.sendall(msg)
        sock.close()
    except Exception as e:
        pass  # Silently fail if nvim not available

def get_breakpoints():
    """Get list of breakpoints"""
    bps = []
    for bp in gdb.breakpoints() or []:
        if bp.location:
            # Parse file:line from location
            loc = bp.location
            file, line = None, None
            if ':' in loc:
                parts = loc.rsplit(':', 1)
                file = parts[0]
                try:
                    line = int(parts[1])
                except:
                    pass
            bps.append({
                'num': bp.number,
                'file': file,
                'line': line,
                'enabled': bp.enabled,
                'location': loc
            })
    return bps

def get_frame():
    """Get current frame info"""
    try:
        frame = gdb.selected_frame()
        sal = frame.find_sal()
        if sal.symtab:
            return {
                'file': sal.symtab.fullname(),
                'line': sal.line,
                'func': frame.name() or '??'
            }
    except:
        pass
    return None

# Cache breakpoints - only rebuild on bp events
_cached_breakpoints = None

def push_state(bp_changed=False):
    """Push debug state to nvim"""
    global _cached_breakpoints
    if bp_changed or _cached_breakpoints is None:
        _cached_breakpoints = get_breakpoints()
    state = {
        'breakpoints': _cached_breakpoints,
        'frame': get_frame()
    }
    state_json = json.dumps(state)
    escaped = state_json.replace("\\", "\\\\").replace("'", "\\'")
    send_to_nvim(f"require('neo-mittens.debug').on_gdb_state('{escaped}')")

def on_stop(event):
    push_state(bp_changed=False)

def on_bp_change(event):
    push_state(bp_changed=True)

gdb.events.stop.connect(on_stop)
gdb.events.breakpoint_created.connect(on_bp_change)
gdb.events.breakpoint_deleted.connect(on_bp_change)
gdb.events.breakpoint_modified.connect(on_bp_change)

# Command for nvim to request state (polling)
class PushState(gdb.Command):
    """Push current debug state to nvim"""
    def __init__(self):
        super().__init__("push_state", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        push_state()

PushState()

# Start debug session: kill existing, load file if needed, run/start
class StartDebug(gdb.Command):
    """Start debug: start_debug <program> [-- args]"""
    def __init__(self):
        super().__init__("start_debug", gdb.COMMAND_RUNNING)

    def invoke(self, arg, from_tty):
        import os

        # Parse program and args
        parts = arg.split(' -- ', 1)
        program = parts[0].strip()
        args = parts[1].strip() if len(parts) > 1 else ''

        if not program:
            print("Usage: start_debug <program> [-- args]")
            return

        # Disable confirmations for the whole operation
        gdb.execute('set confirm off')

        # Kill any running inferior
        try:
            inf = gdb.selected_inferior()
            if inf and inf.pid != 0:
                gdb.execute('kill', to_string=True)
        except:
            pass

        # Load file only if different
        try:
            current = gdb.current_progspace().filename
            current = os.path.abspath(current) if current else None
        except:
            current = None

        new_abs = os.path.abspath(program)
        if current != new_abs:
            gdb.execute(f'file {program}')

        # Set args if provided
        if args:
            gdb.execute(f'set args {args}')
        else:
            gdb.execute('set args')  # Clear args if none provided

        # Start or run based on breakpoints
        bps = gdb.breakpoints()
        if bps and len(bps) > 0:
            gdb.execute('run')
        else:
            gdb.execute('start')

        # Re-enable confirmations
        gdb.execute('set confirm on')

StartDebug()
end

# Listen for commands from nvim via named pipe
python
import threading
import os

def get_project_pipe():
    """Get pipe path based on cwd (matches nvim's logic)"""
    if os.environ.get('GDB_PIPE'):
        return os.environ['GDB_PIPE']
    cwd = os.getcwd()
    project = os.path.basename(cwd)
    return f'/tmp/gdb-{project}.pipe'

def listen_pipe():
    pipe_path = get_project_pipe()
    if not os.path.exists(pipe_path):
        os.mkfifo(pipe_path)
    print(f"Listening on {pipe_path}")
    while True:
        try:
            with open(pipe_path, 'r') as pipe:
                for line in pipe:
                    cmd = line.strip()
                    if cmd:
                        gdb.post_event(lambda c=cmd: gdb.execute(c))
        except:
            pass

t = threading.Thread(target=listen_pipe, daemon=True)
t.start()
end
