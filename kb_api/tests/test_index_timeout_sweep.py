import asyncio
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest

from kb_api.api import config, main


def test_index_task_timeout_reads_yaml_and_rejects_nonpositive_values(tmp_path):
    config_file = tmp_path / "rag.yaml"
    config_file.write_text("indexer:\n  task_timeout: 900\n", encoding="utf-8")
    assert config.load_index_task_timeout(config_file) == 900

    config_file.write_text("indexer:\n  task_timeout: 0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="task_timeout"):
        config.load_index_task_timeout(config_file)


def test_index_timeout_sweep_checks_immediately_and_stops_on_cancel():
    now = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
    called = Event()

    class Files:
        def __init__(self):
            self.cutoffs = []

        def expire_indexing_files(self, cutoff):
            self.cutoffs.append(cutoff)
            called.set()
            return 1

    files = Files()

    async def run():
        task = asyncio.create_task(main.run_index_timeout_sweep(files, 900, interval_seconds=3600, now=lambda: now))
        assert await asyncio.to_thread(called.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert files.cutoffs == [now - timedelta(minutes=15)]
