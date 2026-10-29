from scripts.benchmark_railway_agent import summarize


def test_nearest_rank_p95_and_raw_order():
    result = summarize([5, 1, 3, 4, 2])
    assert result == {
        "n": 5, "raw_ms": [5, 1, 3, 4, 2],
        "p50_ms": 3, "p95_ms": 5, "max_ms": 5,
    }


def test_thirty_samples_use_the_29th_sorted_value_for_p95():
    result = summarize([float(value) for value in range(30, 0, -1)])
    assert result["p95_ms"] == 29
