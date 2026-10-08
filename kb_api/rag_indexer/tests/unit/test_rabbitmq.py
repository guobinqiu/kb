from types import SimpleNamespace

import kb_api.rag_indexer.rabbitmq as rabbitmq
from kb_api.rag_indexer.rabbitmq import RabbitIndexWorker


class Channel:
    def __init__(self):
        self.acked = []
        self.nacked = []

    def basic_ack(self, delivery_tag):
        self.acked.append(delivery_tag)

    def basic_nack(self, delivery_tag, requeue):
        self.nacked.append((delivery_tag, requeue))


def test_worker_consumes_in_foreground_and_closes_connection(monkeypatch):
    calls = []
    worker = RabbitIndexWorker(object(), "amqp://localhost", task_queue="tasks", callback_url="http://kb_api/result", service_api_key="service-key")
    channel = SimpleNamespace(
        queue_declare=lambda **kwargs: calls.append(("declare", kwargs)),
        basic_qos=lambda **kwargs: calls.append(("qos", kwargs)),
        basic_consume=lambda **kwargs: calls.append(("consume", kwargs["queue"])),
    )

    class Connection:
        is_open = True

        def channel(self):
            return channel

        def process_data_events(self, **kwargs):
            calls.append("events")
            worker.stop()

        def close(self):
            self.is_open = False
            calls.append("close")

    monkeypatch.setattr(rabbitmq.pika, "BlockingConnection", lambda params: Connection())
    worker.run()
    assert calls == [("declare", {"queue": "tasks", "durable": True}), ("qos", {"prefetch_count": 1}), ("consume", "tasks"), "events", "close"]


def test_worker_acks_task_after_result_callback_success(monkeypatch):
    monkeypatch.setattr("kb_api.rag_indexer.rabbitmq.time.sleep", lambda _seconds: None)
    worker = RabbitIndexWorker(object(), "amqp://localhost", task_queue="tasks", callback_url="http://kb_api/result", service_api_key="service-key")
    worker._consumer = SimpleNamespace(handle=lambda value: None)
    channel = Channel()

    worker._on_message(channel, SimpleNamespace(delivery_tag="tag-1"), None, b'{"file_id":"file-1"}')

    assert channel.acked == ["tag-1"]
    assert channel.nacked == []


def test_worker_requeues_task_when_result_callback_fails(monkeypatch):
    monkeypatch.setattr("kb_api.rag_indexer.rabbitmq.time.sleep", lambda _seconds: None)

    def fail(_value):
        raise RuntimeError("callback unavailable")

    worker = RabbitIndexWorker(object(), "amqp://localhost", task_queue="tasks", callback_url="http://kb_api/result", service_api_key="service-key")
    worker._consumer = SimpleNamespace(handle=fail)
    channel = Channel()

    worker._on_message(channel, SimpleNamespace(delivery_tag="tag-1"), None, b'{"file_id":"file-1"}')

    assert channel.acked == []
    assert channel.nacked == [("tag-1", True)]
