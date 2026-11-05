"""Measure a running stand; output timings and tool status, never source rows."""
import argparse
import json
from pathlib import Path
from statistics import median
from time import perf_counter

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--source-id', required=True)
    parser.add_argument('--repeat', type=int, choices=range(1, 11), default=3)
    parser.add_argument('--question', default='Вызови get_source_schema для выбранного источника и кратко перечисли названия его столбцов. Ответь по-русски.')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    records = []
    with httpx.Client(base_url=args.url, timeout=1800, trust_env=False) as client:
        for index in range(args.repeat):
            start = perf_counter()
            record = {'run': index + 1}
            try:
                response = client.post('/agent/ask', json={'question': args.question, 'source_ids': [args.source_id]})
                record.update(elapsed_ms=(perf_counter() - start) * 1000, status=response.status_code)
                response.raise_for_status()
                data = response.json()
                record.update(timing=data.get('timing'), answer_chars=len(data['answer']), steps=data['steps'],
                              tools=[{'name': t['tool_name'], 'ok': t['ok']} for t in data['tool_results']])
            except httpx.HTTPError as exc:
                record.update(error=type(exc).__name__, elapsed_ms=(perf_counter() - start) * 1000)
            records.append(record)
            print(json.dumps(record, ensure_ascii=False), flush=True)
    successful = [r['elapsed_ms'] for r in records if r.get('status') == 200]
    report = {'runs': records, 'median_ms': median(successful) if successful else None,
              'note': 'Sequential requests; first is not assumed cold, later requests may use prompt cache. Check answer/tool correctness separately.'}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('median_ms', report['median_ms'])
    return 1 if any('error' in r for r in records) else 0


if __name__ == '__main__':
    raise SystemExit(main())
