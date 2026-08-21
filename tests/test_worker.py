from tools.worker import Worker


def test_worker_emits_progress_and_result():
    progress = []
    results = []

    def task(worker, value):
        worker.report_progress({"percent": 50})
        return value * 2

    worker = Worker(task, 21)
    worker.progress.connect(progress.append)
    worker.result.connect(results.append)

    worker.run()

    assert progress == [{"percent": 50}]
    assert results == [42]


def test_worker_emits_error_without_result():
    errors = []
    results = []

    def task(worker):
        raise RuntimeError("boom")

    worker = Worker(task)
    worker.error.connect(errors.append)
    worker.result.connect(results.append)

    worker.run()

    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert results == []


def test_worker_emits_cancelled_when_cancelled_before_run():
    cancelled = []
    results = []

    worker = Worker(lambda worker: "should not run")
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.result.connect(results.append)
    worker.cancel()

    worker.run()

    assert cancelled == [True]
    assert results == []
