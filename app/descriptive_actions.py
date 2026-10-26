"""Bounded, source-independent analytical actions; all facts come from SQL."""
from time import perf_counter
import re

from app.contracts.v1 import AgentResponse, AnalysisPlan
from app.models import ToolResult
from app.safe_sql import SafeQueryError


ACTION_NAMES = frozenset({'frequencies', 'duplicates', 'outliers', 'preview'})


def descriptive_route(question: str) -> str | None:
    """Bypass inference only for complete unfiltered requests; never substrings."""
    phrase = re.sub(r'\s+', ' ', question.casefold().replace('ё', 'е')).strip().rstrip('?! .')
    # Strip only a conversational prefix; still require a complete unfiltered
    # request. "А ... за июль" must keep its filter and go through planning.
    phrase = re.sub(r'^(?:а(?: теперь)?|теперь)\s+', '', phrase)
    patterns = {
        'frequencies': r'(?:какие значения (?:встречаются|попадаются) чаще всего|(?:покажи |выведи )?(?:самые частые|наиболее частые) значения|какие значения чаще встречаются|покажи частоты значений)',
        'duplicates': r'(?:есть ли (?:тут |здесь )?(?:повторяющиеся данные|дубликаты|повторяющиеся строки)|найди (?:полные )?дубликаты(?: строк)?)',
        'outliers': r'(?:есть ли (?:тут |здесь )?(?:аномалии|выбросы)|(?:найди|покажи) (?:аномалии|выбросы))',
        'preview': r'покажи первые (?:10 |десять )?строк(?:и)?',
    }
    return next((action for action, pattern in patterns.items() if re.fullmatch(pattern, phrase)), None)


def markdown_cell(value: str) -> str:
    return re.sub(r'([\\`*_{}\[\]()<>!|])', r'\\\1', value).replace('\n', ' ').replace('\r', ' ')


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def render_table(result):
    def cell(value):
        return markdown_cell(str(value)) if value is not None else 'NULL'
    return '\n'.join([
        '| ' + ' | '.join(cell(c.name) for c in result.columns) + ' |',
        '| ' + ' | '.join('---' for _ in result.columns) + ' |',
        *['| ' + ' | '.join(cell(v) for v in row) + ' |' for row in result.rows],
    ])


def descriptive_answer(sources, intent, columns, source_id, schema, timing, request_id, steps=0):
    fields = schema.objects[0].fields if schema.objects else []
    by_name = {f.name: f for f in fields}
    if len(columns) > 8 or len(set(columns)) != len(columns) or any(c not in by_name for c in columns):
        raise SafeQueryError('QUERY_REJECTED')
    source = sources.catalog.get_source(source_id)
    if source is None or source.schema_version != schema.version:
        raise SafeQueryError('QUERY_REJECTED')
    started = perf_counter()
    trace, results, sqls, parts = [], [], [], []

    def execute(sql, limit):
        remaining = 10 - (perf_counter() - started)
        if remaining <= 0:
            raise SafeQueryError('QUERY_TIMEOUT')
        result = sources.query(source_id, sql, row_limit=limit, timeout_seconds=remaining)
        if not result.provenance or any(
            p.source_id != source_id or p.snapshot_id != (source.snapshot_id or 'legacy')
            or p.schema_version != source.schema_version for p in result.provenance
        ):
            raise SafeQueryError('QUERY_REJECTED')
        results.append(result)
        trace.append(ToolResult(tool_name='query_data', ok=True, data=result))
        sqls.append(sql)
        return result

    try:
        if intent == 'frequencies':
            candidates = [f.name for f in fields if f.inferred_type in {'string', 'boolean'} and not f.is_identifier_candidate]
            candidates = candidates or [f.name for f in fields if not f.is_identifier_candidate] or list(by_name)
            chosen = columns or candidates[:8]
            parts.append('Пять наиболее частых непустых значений отдельно по каждому выбранному полю. '
                         'Частоты посчитаны по всем строкам источника; NULL и пустые строки исключены. '
                         'При равных частотах значения упорядочены по тексту.')
            if not columns:
                parts.append('Поле не указано: для обзора выбраны ' + ', '.join('«' + markdown_cell(c) + '»' for c in chosen) +
                             '. Это обзор отдельных полей, не частота сочетаний между ними.' +
                             (' Остальные поля не включены: обзор ограничен восемью полями.' if len(candidates) > 8 else ''))
            for name in chosen:
                col = quote(name)
                # Count first also makes the existing chart renderer select the
                # measure rather than numeric-looking identifiers such as 001.
                result = execute(f'SELECT COUNT(*) AS frequency, {col} AS value FROM source '
                                 f"WHERE {col} IS NOT NULL AND TRIM({col}) <> '' "
                                 f'GROUP BY {col} ORDER BY frequency DESC, value ASC LIMIT 5', 5)
                parts.append('Поле «' + markdown_cell(name) + '»\n\n' +
                             (render_table(result) if result.rows else 'Непустых значений нет.'))
            parts.append('Для графика откройте результаты инструментов и выберите «Столбцы».')
        elif intent == 'duplicates':
            # Full-row duplicates by default; an explicit key changes the grain.
            keys = columns or list(by_name)
            if not keys:
                raise SafeQueryError('QUERY_REJECTED')
            group = ', '.join(quote(c) for c in keys)
            result = execute('SELECT COUNT(*) AS duplicate_groups, COALESCE(SUM(n - 1), 0) AS extra_rows '
                             f'FROM (SELECT COUNT(*) AS n FROM source GROUP BY {group} HAVING COUNT(*) > 1) AS repeated', 1)
            parts.append(('Совпадение по полям: ' + ', '.join(markdown_cell(c) for c in keys) + '.' if columns else
                          'Проверены полные дубликаты строк: должны совпасть все поля, включая ID. '
                          'Повторение одного ID — другой анализ, для него укажите поле.') +
                         '\n\nЧисло групп повторов и число лишних строк сверх первой в каждой группе:')
            parts.append(render_table(result))
        elif intent == 'outliers':
            numeric = [
                field.name for field in fields
                if field.inferred_type in {'integer', 'number'}
                and not field.is_identifier_candidate
            ]
            numeric = numeric or [
                field.name for field in fields
                if field.inferred_type in {'integer', 'number'}
            ]
            chosen = columns or numeric[:1]
            if len(chosen) != 1 or by_name[chosen[0]].inferred_type not in {'integer', 'number'}:
                raise SafeQueryError('QUERY_REJECTED')
            name = chosen[0]
            col = quote(name)
            value = f"TRY_CAST(NULLIF(REPLACE(TRIM(CAST({col} AS VARCHAR)), ',', '.'), '') AS DOUBLE)"
            stats = execute(
                'WITH numeric_values AS ('
                f'SELECT {value} AS value FROM source'
                ') SELECT COUNT(*) AS observed_rows, '
                'quantile_cont(value, 0.25) AS q1, quantile_cont(value, 0.75) AS q3 '
                'FROM numeric_values WHERE value IS NOT NULL',
                1,
            )
            parts.append(
                'Метод: межквартильный размах (IQR). Кандидатами считаются значения ниже '
                'Q1 − 1,5×IQR или выше Q3 + 1,5×IQR. Группа сравнения — все корректные '
                f'числовые значения поля «{markdown_cell(name)}»; пропуски и нечисловые значения исключены.'
            )
            if not stats.rows or stats.rows[0][0] == 0 or stats.rows[0][1] is None or stats.rows[0][2] is None:
                parts.append('Для расчёта нет корректных числовых значений.')
            elif stats.rows[0][0] < 4:
                parts.append(
                    'Для IQR-анализа нужно минимум 4 корректных числовых значения; '
                    f'найдено {stats.rows[0][0]}. Кандидаты не определялись.'
                )
            elif stats.rows[0][2] <= stats.rows[0][1]:
                parts.append(
                    'IQR равен нулю: все корректные значения находятся на одном уровне. '
                    'Порог для поиска кандидатов не определяется.'
                )
            else:
                candidates = execute(
                    'WITH numeric_values AS ('
                    f'SELECT {value} AS value FROM source'
                    '), bounds AS ('
                    'SELECT quantile_cont(value, 0.25) AS q1, quantile_cont(value, 0.75) AS q3 '
                    'FROM numeric_values WHERE value IS NOT NULL'
                    ') SELECT value AS candidate_value, q1, q3, '
                    '(q1 - 1.5 * (q3 - q1)) AS lower_threshold, '
                    '(q3 + 1.5 * (q3 - q1)) AS upper_threshold '
                    'FROM numeric_values CROSS JOIN bounds '
                    'WHERE value IS NOT NULL AND q3 > q1 AND '
                    '(value < q1 - 1.5 * (q3 - q1) OR value > q3 + 1.5 * (q3 - q1)) '
                    'ORDER BY value ASC LIMIT 20',
                    20,
                )
                parts.extend([
                    'Параметры сравнения:',
                    render_table(stats),
                    'Найденные кандидаты:' if candidates.rows else 'Кандидатов по этому порогу не найдено.',
                ])
                if candidates.rows:
                    parts.append(render_table(candidates))
            parts.append('Это статистическое отклонение, а не установленная причина. Строки не удалены и не изменены.')
        elif intent == 'preview':
            projection = ', '.join(quote(c) for c in columns) if columns else '*'
            result = execute(f'SELECT {projection} FROM source LIMIT 10', 10)
            parts.extend(['Первые 10 строк, без сортировки. Это предпросмотр, не статистика всего источника.',
                          render_table(result) if result.rows else 'В источнике нет строк.'])
        else:
            raise SafeQueryError('QUERY_REJECTED')
        return AgentResponse(request_id=request_id, status='answered', answer_kind='computed',
                             answer='\n\n'.join(parts), steps=steps, timing=timing,
                             analysis=AnalysisPlan(intent=intent, sql=sqls[0] if len(sqls) == 1 else None,
                                                   explanation='Выполненные запросы:\n' + '\n'.join(sqls)),
                             results=results, tool_results=trace)
    finally:
        timing.tools_ms += (perf_counter() - started) * 1000
