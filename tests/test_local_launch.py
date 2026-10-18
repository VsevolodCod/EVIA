"""Smoke the built app over HTTP, including launcher shutdown (no real LLM needed)."""

import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


def unused_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


@pytest.mark.parametrize("dev", [False, True], ids=["production", "development"])
def test_app_runs_csv_to_mock_over_http_and_stops(tmp_path, dev):
    if not dev and not (ROOT / 'frontend' / 'dist' / 'index.html').is_file():
        pytest.skip('Run npm --prefix frontend run build before the production smoke test')
    port = unused_port()
    ui_port = unused_port() if dev else port
    while dev and ui_port == port:
        ui_port = unused_port()
    environment = {**os.environ, 'LLM_PROVIDER': 'mock',
                   'BI_DATA_DIR': str(tmp_path / 'data'),
                   'CATALOG_DB_PATH': str(tmp_path / 'catalog.sqlite3'),
                   'CHAT_DB_PATH': str(tmp_path / 'chats.sqlite3'),
                   'PYTHONIOENCODING': 'utf-8'}
    with (tmp_path / 'server.log').open('w') as log:
        command = [sys.executable, str(ROOT / 'scripts' / 'run.py'), '--port', str(port)]
        if dev:
            command += ['--dev', '--ui-port', str(ui_port)]
        process = subprocess.Popen(command,
                                   cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{ui_port}', timeout=5) as client:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    assert process.poll() is None, (tmp_path / 'server.log').read_text(encoding='utf-8')
                    try:
                        if client.get('/health').status_code == 200:
                            break
                    except httpx.TransportError:
                        time.sleep(0.05)
                else:
                    pytest.fail('Application did not become ready within 15 seconds')
                page = client.get('/')
                assert page.status_code == 200
                assert 'text/html' in page.headers['content-type']
                assets = re.findall(r'(?:src|href)="(/assets/[^"<>]+)"', page.text)
                if dev:
                    assert '/@vite/client' in page.text
                    assert client.get('/src/main.tsx').status_code == 200
                else:
                    assert assets, 'Built HTML must reference bundled local assets'
                for asset in assets:
                    assert client.get(asset).status_code == 200
                assert client.get('/health').json()['llm_provider'] == 'mock'
                upload = client.post('/sources/csv', files={'file': ('sales.csv', (ROOT / 'sample-data' / 'sales.csv').read_bytes(), 'text/csv')})
                assert upload.status_code == 200
                source_id = upload.json()['source_id']
                assert client.get(f'/sources/{source_id}/preview').json()[0]['order_id'] == '0001'
                assert client.get(f'/sources/{source_id}/schema').json()['objects'][0]['row_count'] == 8
                assert client.get(f'/sources/{source_id}/profile').json()['sample_size'] == 8
                answer = client.post('/agent/ask', json={'question': 'Что есть в данных?', 'source_ids': [source_id]})
                assert answer.status_code == 200
                assert answer.json()['answer']
                assert answer.json()['tool_results'][0]['data'][0]['source_id'] == source_id
                chat = client.post('/chats', json={'title': 'Synthetic conversation'})
                assert chat.status_code == 201
                chat_id = chat.json()['chat_id']
                for question in ('First turn', 'Follow-up'):
                    continued = client.post('/agent/chat', params={'chat_id': chat_id},
                                            json={'question': question, 'source_ids': [source_id]})
                    assert continued.status_code == 200
                    assert continued.json()['chat_id'] == chat_id
                assert client.get(f'/chats/{chat_id}').json()['total_messages'] == 4
        finally:
            try:
                if process.poll() is None:
                    if os.name == 'nt':
                        process.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        process.terminate()
                process.wait(timeout=15)
            finally:
                if process.poll() is None:
                    if os.name == 'nt':
                        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], check=False)
                    else:
                        process.kill()
                    process.wait(timeout=5)
        assert process.returncode == 0, (tmp_path / 'server.log').read_text(encoding='utf-8')
        for closed_port in {port, ui_port}:
            with socket.socket() as check:
                assert check.connect_ex(('127.0.0.1', closed_port)) != 0, 'Port remained open after launcher shutdown'
