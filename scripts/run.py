"""Run the locally prepared application; no dependency downloads at startup."""

import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def build_commands(
    root: Path, *, dev: bool, host: str, port: int, ui_port: int,
    python: str, npm: str | None,
) -> list[list[str]]:
    if dev and port == ui_port:
        raise ValueError('Порты API и интерфейса должны различаться.')
    backend = [python, '-m', 'uvicorn', 'app.main:app', '--host', host, '--port', str(port)]
    if not dev:
        if not (root / 'frontend' / 'dist' / 'index.html').is_file():
            raise ValueError('Сначала соберите интерфейс: npm --prefix frontend run build')
        return [backend]
    if not npm:
        raise ValueError('Для разработки нужны Node.js и npm в PATH.')
    if not (root / 'frontend' / 'node_modules' / 'vite').is_dir():
        raise ValueError('Установите зависимости: npm ci --prefix frontend')
    if os.name == 'nt':
        # npm.cmd can exit before Vite and orphan the listening process on Windows.
        # Own the Vite process directly so shutdown always targets the server.
        node = shutil.which('node')
        if not node:
            raise ValueError('Для разработки нужны Node.js и npm в PATH.')
        return [backend, [node, str(root / 'frontend' / 'node_modules' / 'vite' / 'bin' / 'vite.js'),
                          str(root / 'frontend'), '--host', host, '--port', str(ui_port), '--strictPort']]
    return [backend, [npm, '--prefix', 'frontend', 'run', 'dev', '--',
                      '--host', host, '--port', str(ui_port), '--strictPort']]


def stop_processes(processes: list[subprocess.Popen]) -> None:
    """Terminate only process groups started by this launcher, including npm children."""
    for process in reversed(processes):
        if os.name == 'nt':
            if process.poll() is None:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
    if os.name != 'nt':
        # A reaped group leader does not imply that its descendants have stopped.
        # Track the owned groups for the entire grace period, then kill survivors.
        remaining = list(processes)
        deadline = time.monotonic() + 5
        while remaining and time.monotonic() < deadline:
            alive = []
            for process in remaining:
                process.poll()  # Reap a terminated leader while checking its group.
                try:
                    os.killpg(process.pid, 0)
                    alive.append(process)
                except (ProcessLookupError, PermissionError):
                    pass
            remaining = alive
            if remaining:
                time.sleep(0.05)
        for process in remaining:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
    for process in reversed(processes):
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def port_number(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError('Порт должен быть от 1 до 65535.')
    return number


def main() -> int:
    parser = argparse.ArgumentParser(description='Локальный запуск EVIA')
    parser.add_argument('--dev', action='store_true', help='FastAPI + Vite с обновлением интерфейса')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=port_number, default=8000, help='Порт API / готового приложения')
    parser.add_argument('--ui-port', type=port_number, default=5173, help='Порт Vite в режиме --dev')
    args = parser.parse_args()
    try:
        commands = build_commands(ROOT, dev=args.dev, host=args.host, port=args.port,
                                  ui_port=args.ui_port, python=sys.executable,
                                  npm=shutil.which('npm'))
        if importlib.util.find_spec('uvicorn') is None:
            raise ValueError('Активируйте .venv и установите зависимости: python -m pip install -r requirements.txt')
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    connect_host = '127.0.0.1' if args.host == '0.0.0.0' else ('::1' if args.host == '::' else args.host)
    url_host = f'[{connect_host}]' if ':' in connect_host else connect_host
    environment = {**os.environ, 'BI_API_TARGET': f'http://{url_host}:{args.port}'}
    print(f'EVIA: http://{url_host}:{args.ui_port if args.dev else args.port}', flush=True)
    print('Ctrl+C останавливает все процессы этого запуска.', flush=True)
    processes: list[subprocess.Popen] = []
    stopping = False

    def request_stop(signum, frame):
        nonlocal stopping
        stopping = True

    stop_signals = [signal.SIGINT, signal.SIGTERM]
    if os.name == 'nt':
        stop_signals.append(signal.SIGBREAK)
    old_handlers = {sig: signal.signal(sig, request_stop) for sig in stop_signals}
    try:
        for command in commands:
            options = {'start_new_session': True} if os.name != 'nt' else {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
            processes.append(subprocess.Popen(command, cwd=ROOT, env=environment, **options))
        while not stopping:
            for process in processes:
                code = process.poll()
                if code is not None:
                    print(f'Процесс завершился (код {code}); останавливаем приложение.', file=sys.stderr)
                    return code or 1
            time.sleep(0.2)
        return 0
    except OSError as exc:
        print(f'Не удалось запустить приложение: {exc}', file=sys.stderr)
        return 1
    finally:
        stop_processes(processes)
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    raise SystemExit(main())
