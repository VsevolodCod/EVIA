from scripts.run import build_commands
import pytest


def test_production_requires_build_and_does_not_need_node(tmp_path):
    with pytest.raises(ValueError, match='npm.*build'):
        build_commands(tmp_path, dev=False, host='127.0.0.1', port=8000, ui_port=5173, python='python', npm=None)
    (tmp_path / 'frontend' / 'dist').mkdir(parents=True)
    (tmp_path / 'frontend' / 'dist' / 'index.html').write_text('app')
    commands = build_commands(tmp_path, dev=False, host='127.0.0.1', port=8000, ui_port=5173, python='python', npm=None)
    assert commands == [['python', '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000']]


def test_development_requires_dependencies_and_uses_strict_ports(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr('scripts.run.shutil.which', lambda _: 'node.exe')
    with pytest.raises(ValueError, match='Node.js'):
        build_commands(tmp_path, dev=True, host='127.0.0.1', port=8000, ui_port=5173, python='python', npm=None)
    with pytest.raises(ValueError, match='npm ci'):
        build_commands(tmp_path, dev=True, host='127.0.0.1', port=8000, ui_port=5173, python='python', npm='npm')
    (tmp_path / 'frontend' / 'node_modules' / 'vite').mkdir(parents=True)
    commands = build_commands(tmp_path, dev=True, host='127.0.0.1', port=8100, ui_port=5200, python='python', npm='npm')
    assert commands[0][-1] == '8100'
    if os.name == 'nt':
        assert commands[1] == ['node.exe', str(tmp_path / 'frontend' / 'node_modules' / 'vite' / 'bin' / 'vite.js'), str(tmp_path / 'frontend'), '--host', '127.0.0.1', '--port', '5200', '--strictPort']
    else:
        assert commands[1] == ['npm', '--prefix', 'frontend', 'run', 'dev', '--', '--host', '127.0.0.1', '--port', '5200', '--strictPort']


def test_dev_ports_cannot_collide(tmp_path):
    with pytest.raises(ValueError, match='различаться'):
        build_commands(tmp_path, dev=True, host='127.0.0.1', port=8000, ui_port=8000, python='python', npm='npm')


def test_cleanup_stops_descendant_even_after_parent_exits(tmp_path):
    import os
    import signal
    import subprocess
    import sys
    import time
    from scripts.run import stop_processes

    if os.name == 'nt':
        pytest.skip('POSIX process-group regression; Windows uses taskkill /T')
    heartbeat = tmp_path / 'heartbeat'
    child_code = '''
import signal, sys, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
p = Path(sys.argv[1])
i = 0
while True:
    p.write_text(str(i))
    i += 1
    time.sleep(0.02)
'''
    parent_code = '''
import subprocess, sys, time
subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]])
time.sleep(60)
'''
    parent = subprocess.Popen([sys.executable, '-c', parent_code, child_code, str(heartbeat)], start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while not heartbeat.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert heartbeat.exists(), 'Test descendant did not become ready'
        stop_processes([parent])
        assert parent.poll() is not None
        before = heartbeat.read_text()
        time.sleep(0.15)
        assert heartbeat.read_text() == before, 'Owned descendant survived shutdown'
    finally:
        try:
            os.killpg(parent.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        parent.wait(timeout=5)
