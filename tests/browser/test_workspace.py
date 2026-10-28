"""Opt-in browser acceptance against a real, isolated FastAPI in mock mode.

BI_BROWSER_TESTS=1 python -m pytest tests/browser -q
BI_BROWSER_CHANNEL=msedge uses an installed Edge; omit for Playwright Chromium.
"""

import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import pytest
from urllib.parse import urlparse, parse_qs

pytestmark = pytest.mark.skipif(os.getenv('BI_BROWSER_TESTS') != '1', reason='Opt-in browser acceptance')
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def server(tmp_path):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    environment = {**os.environ, 'LLM_PROVIDER': 'mock',
                   'BI_DATA_DIR': str(tmp_path / 'data'),
                   'CATALOG_DB_PATH': str(tmp_path / 'catalog.db'),
                   'CHAT_DB_PATH': str(tmp_path / 'chats.db'),
                   'PYTHONIOENCODING': 'utf-8'}
    with (tmp_path / 'server.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(
            [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)],
            cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
        try:
            url = f'http://127.0.0.1:{port}'
            with httpx.Client(base_url=url, timeout=1) as client:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    assert process.poll() is None, (tmp_path / 'server.log').read_text(encoding='utf-8')
                    try:
                        if client.get('/health').status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail('Browser test API did not start')
            yield url
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_real_workspace_keyboard_mobile_and_safe_markdown(server):
    from playwright.sync_api import sync_playwright, expect

    artifacts = ROOT / 'frontend' / 'test-results'
    artifacts.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv('BI_BROWSER_CHANNEL') or None)
        try:
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.set_default_timeout(10000)
            errors = []
            external = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: external.append(request.url) if not request.url.startswith(server + '/') else None)
            page.goto(server)
            expect(page).to_have_title('EVIA')
            expect(page.get_by_text('Нет источников', exact=True)).to_be_visible()
            page.keyboard.press('Tab')
            expect(page.get_by_role('link', name='Перейти к данным')).to_be_focused()
            upload = page.get_by_role('button', name='Выбрать CSV', exact=True)
            upload.focus()
            with page.expect_file_chooser() as chooser:
                upload.click()
            chooser.value.set_files(ROOT / 'sample-data' / 'sales.csv')
            expect(page.get_by_role('heading', name='sales')).to_be_visible()
            page.get_by_role('button', name='Данные', exact=True).click()
            expect(page.get_by_role('region', name='Предпросмотр источника').get_by_text('0001', exact=True)).to_be_visible()
            source_id = page.request.get(server + '/sources').json()[0]['source_id']
            page.get_by_role('button', name='Схема', exact=True).click()
            expect(page.get_by_role('heading', name='Структура источника')).to_be_visible()
            page.get_by_role('button', name='Столбцы', exact=True).click()
            expect(page.get_by_role('heading', name='Столбцы данных')).to_be_visible()
            question = page.get_by_role('textbox', name='Ваш вопрос')
            first_question = 'Что есть в данных? ' * 12
            question.fill(first_question)
            with page.expect_request('**/agent/chat?*') as sent:
                question.press('Control+Enter')
            assert sent.value.post_data_json == {'question': first_question.strip(), 'source_ids': [source_id]}
            chat_id = parse_qs(urlparse(sent.value.url).query)['chat_id'][0]
            expect(page.get_by_role('region', name='Ответ EVIA').get_by_text('Тестовый режим показал первые строки выбранного источника.', exact=False)).to_be_visible()
            assert page.locator('.history-list').evaluate('(node) => node.scrollWidth <= node.clientWidth')
            page.get_by_role('button', name='Открыть результат', exact=True).click()
            expect(page.get_by_role('region', name='Таблица результата').get_by_text('0001', exact=True)).to_be_visible()
            page.get_by_text('Таблица и детали расчёта', exact=True).click()
            expect(page.get_by_role('region', name='Результат preview_data').get_by_text('0001', exact=True)).to_be_visible()
            # Server source binding and the complete tool result survive without the old browser cache.
            page.evaluate("localStorage.removeItem('evia.chat-sources.v1')")
            page.reload()
            page.get_by_role('button', name='sales', exact=True).click()
            page.get_by_role('button', name=first_question.strip()).click()
            expect(page.get_by_role('region', name='Ответ EVIA').get_by_text('Тестовый режим показал первые строки выбранного источника.', exact=False)).to_be_visible()
            page.get_by_role('button', name='Открыть результат', exact=True).click()
            page.get_by_text('Таблица и детали расчёта', exact=True).click()
            expect(page.get_by_role('region', name='Результат preview_data').get_by_text('0001', exact=True)).to_be_visible()
            page.screenshot(path=str(artifacts / 'desktop.png'), full_page=True)

            page.emulate_media(reduced_motion='reduce')
            assert page.locator('.evia-mascot img').evaluate_all('(nodes) => nodes.every(n => getComputedStyle(n).animationName === "none")')

            page.get_by_label('Загрузить CSV').set_input_files({
                'name': 'second.csv', 'mimeType': 'text/csv', 'buffer': b'id,value\n0099,5\n'})
            expect(page.get_by_role('heading', name='second')).to_be_visible()
            page.get_by_role('button', name='Данные', exact=True).click()
            expect(page.get_by_role('region', name='Предпросмотр источника').get_by_text('0099')).to_be_visible()
            expect(page.get_by_text('Тестовый режим показал первые строки выбранного источника.', exact=False)).to_have_count(0)
            page.get_by_role('button', name='sales', exact=True).click()
            expect(page.get_by_text('Тестовый режим показал первые строки выбранного источника.', exact=False)).to_be_visible()

            # Synthetic hostile response verifies browser rendering, not model quality.
            def hostile_answer(route):
                requested_chat_id = parse_qs(urlparse(route.request.url).query)['chat_id'][0]
                route.fulfill(json={
                    'chat_id': requested_chat_id,
                    'answer': '- Пункт проверки\n\n| Поле | Значение |\n| --- | --- |\n| ID | 0001 |\n\n```sql\nSELECT 1\n```\n\n<script>window.pwned=true</script>\n\n![remote](https://evil.test/pixel)\n\n[bad](javascript:alert%281%29)',
                    'steps': 1, 'tool_results': [{'tool_name': 'preview_source', 'ok': True, 'data': []}]} )
            page.route('**/agent/chat?*', hostile_answer)
            question.fill('Проверка безопасного Markdown')
            question.press('Control+Enter')
            expect(page.locator('.markdown table')).to_be_visible()
            expect(page.locator('.markdown li')).to_have_text('Пункт проверки')
            expect(page.locator('.markdown pre code')).to_contain_text('SELECT 1')
            expect(page.locator('.markdown img, .markdown script, .markdown a')).to_have_count(0)
            assert page.evaluate('window.pwned') is None
            page.get_by_role('button', name='Открыть результат', exact=True).last.click()
            expect(page.get_by_text('Нет строк для отображения', exact=True)).to_be_visible()
            page.set_viewport_size({'width': 390, 'height': 844})
            page.get_by_role('button', name='Чат').click()
            mobile_question = page.get_by_role('textbox', name='Ваш вопрос')
            mobile_question.scroll_into_view_if_needed()
            expect(mobile_question).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(artifacts / 'mobile.png'), full_page=True)
            assert errors == []
            assert external == []
        finally:
            browser.close()


def test_profile_overview_drilldown_search_and_responsive_layout(server):
    from playwright.sync_api import sync_playwright, expect

    artifacts = ROOT / 'frontend' / 'test-results'
    artifacts.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv('BI_BROWSER_CHANNEL') or None)
        try:
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(server)
            page.get_by_label('Загрузить CSV').set_input_files({
                'name': 'retail-demo.csv', 'mimeType': 'text/csv',
                'buffer': ('region,revenue,channel\nСевер,1200,Сайт\nЮг,800,Магазин\n'
                           'Север,1500,Сайт\n,600,Магазин\nЗапад,900,Сайт\nВосток,1100,\n').encode(),
            })
            expect(page.get_by_role('heading', name='retail-demo')).to_be_visible()
            expect(page.locator('.kpi-grid .dashboard-card').first).to_contain_text('6')
            expect(page.get_by_text('Заполненность источника', exact=True)).to_be_visible()
            expect(page.get_by_role('textbox', name='Ваш вопрос')).to_be_in_viewport()
            page.screenshot(path=str(artifacts / 'analytics-overview-desktop.png'), full_page=True)
            for width in [1280, 1024, 768, 390]:
                page.set_viewport_size({'width': width, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Overflow at {width}px'
            page.get_by_role('button', name='Рабочее пространство').click()
            expect(page.get_by_role('navigation', name='Разделы источника')).to_be_visible()
            page.screenshot(path=str(artifacts / 'analytics-overview-mobile.png'), full_page=True)
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.get_by_role('button', name='Качество', exact=True).focus()
            page.keyboard.press('Enter')
            expect(page.get_by_role('heading', name='Качество данных')).to_be_visible()
            page.get_by_role('button', name='Столбцы', exact=True).click()
            field = page.get_by_role('region', name='Столбец region', exact=True)
            field.get_by_text('region', exact=True).click()
            expect(field.get_by_text('Север', exact=True)).to_be_visible()
            search = page.get_by_role('searchbox', name='Поиск столбца')
            search.fill('REVENUE')
            expect(page.get_by_role('region', name='Столбец revenue')).to_be_visible()
            expect(field).to_have_count(0)
            page.screenshot(path=str(artifacts / 'analytics-column-desktop.png'), full_page=True)
            page.get_by_role('button', name='Качество', exact=True).click()
            page.screenshot(path=str(artifacts / 'analytics-quality-desktop.png'), full_page=True)
            page.get_by_role('button', name='Данные', exact=True).click()
            expect(page.get_by_role('region', name='Предпросмотр источника').get_by_text('1200', exact=True)).to_be_visible()
            page.get_by_role('textbox', name='Ваш вопрос').fill('Какие данные доступны?')
            page.get_by_role('button', name='Отправить вопрос').click()
            page.get_by_role('button', name='Открыть результат', exact=True).click()
            expect(page.get_by_role('heading', name='Результат анализа')).to_be_visible()
            expect(page.get_by_role('main').get_by_text('Тестовый режим', exact=False)).to_have_count(0)
            page.get_by_role('button', name='Открыть ответ в чате').click()
            expect(page.get_by_role('region', name='Ответ EVIA')).to_contain_text('Тестовый режим')
            page.screenshot(path=str(artifacts / 'analytics-result-desktop.png'), full_page=True)
            # Reload and choose the same persisted source: the overview uses the same real profile.
            page.reload()
            page.get_by_role('button', name='retail-demo', exact=True).click()
            expect(page.locator('.kpi-grid .dashboard-card').first).to_contain_text('6')
            # New data must clear both search context and old profile immediately.
            page.get_by_label('Загрузить CSV').set_input_files({
                'name': 'second.csv', 'mimeType': 'text/csv', 'buffer': b'id\n1\n2\n',
            })
            expect(page.locator('.kpi-grid .dashboard-card').first).to_contain_text('2')
            page.get_by_role('button', name='Столбцы', exact=True).click()
            expect(page.get_by_role('searchbox', name='Поиск столбца')).to_have_value('')
            expect(page.get_by_role('region', name='Столбец id')).to_be_visible()
            assert errors == []
        finally:
            browser.close()
