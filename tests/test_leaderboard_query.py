from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_leaderboard_matches_officeqa_full_ranking_and_columns() -> None:
    leaderboards = json.loads((ROOT / "leaderboard-query.json").read_text())

    assert leaderboards == [
        {
            "name": "Overall Performance",
            "query": (
                "SELECT id, ROUND(accuracy, 1) AS accuracy, correct, total FROM ("
                "SELECT *, ROW_NUMBER() OVER (PARTITION BY id ORDER BY accuracy DESC, "
                "result_filename ASC) AS rn FROM (SELECT results.participants.agent "
                "AS id, results.filename AS result_filename, (SELECT 100.0 * "
                "SUM(res.score) / NULLIF(SUM(res.max_score), 0) FROM "
                "UNNEST(results.results) AS r(res)) AS accuracy, (SELECT "
                "CAST(SUM(res.score) AS INTEGER) FROM UNNEST(results.results) AS r(res)) "
                "AS correct, (SELECT CAST(SUM(res.max_score) AS INTEGER) FROM "
                "UNNEST(results.results) AS r(res)) AS total FROM results)) WHERE rn = 1 "
                "ORDER BY accuracy DESC, result_filename ASC;"
            ),
        }
    ]
