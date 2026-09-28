from types import SimpleNamespace

from kb_api.rag_indexer.rabbitmq import RabbitIndexWorker


class Channel:
    def __init__(self):
        self.acked = []
        self.nacked = []

    def basic_ack(self, delivery_tag):
        self.acked.append(delivery_tag)

    def basic_nack(self, delivery_tag, requeue):
        self.nacked.append((delivery_tag, requeue))


def test_worker_acks_task_after_result_callback_success(monkeypatch):
    monkeypatch.setattr("kb_api.rag_indexer.rabbitmq.time.sleep", lambda _seconds: None)
    worker = RabbitIndexWorker(object(), "amqp://localhost", task_queue="tasks", callback_url="http://kb_api/result")
    worker._consumer = SimpleNamespace(handle=lambda value: None)
    channel = Channel()

    worker._on_message(channel, SimpleNamespace(delivery_tag="tag-1"), None, b'{"file_id":"file-1"}')

    assert channel.acked == ["tag-1"]
    assert channel.nacked == []


def test_worker_requeues_task_when_result_callback_fails(monkeypatch):
    monkeypatch.setattr("kb_api.rag_indexer.rabbitmq.time.sleep", lambda _seconds: None)

    def fail(_value):
        raise RuntimeError("callback unavailable")

    worker = RabbitIndexWorker(object(), "amqp://localhost", task_queue="tasks", callback_url="http://kb_api/result")
    worker._consumer = SimpleNamespace(handle=fail)
    channel = Channel()

    worker._on_message(channel, SimpleNamespace(delivery_tag="tag-1"), None, b'{"file_id":"file-1"}')

    assert channel.acked == []
    assert channel.nacked == [("tag-1", True)]
