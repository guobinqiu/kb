from types import SimpleNamespace

import httpx
import pytest

from kb_api.rag_indexer.rabbitmq import RabbitIndexWorker


class Channel:
    def __init__(self):
        self.acked = []
        self.nacked = []

    def basic_ack(self, delivery_tag):
        self.acked.append(delivery_tag)

    def basic_nack(self, delivery_tag, requeue):
        self.nacked.append((delivery_tag, requeue))


def worker():
    return RabbitIndexWorker(object(), "amqp://unused", task_queue="tasks", callback_url="http://kb/result")


@pytest.mark.parametrize("response_status", [204, 503])
def test_worker_callback_preserves_ack(monkeypatch, response_status):
    monkeypatch.setattr("kb_api.rag_indexer.rabbitmq.time.sleep", lambda _: None)
    instance = worker()
    requests = []
    results = []
    client = httpx.Client(transport=httpx.MockTransport(
        lambda req: requests.append(req) or httpx.Response(response_status)
    ))
    monkeypatch.setattr("kb_api.rag_indexer.rabbitmq.httpx.Client", lambda **kw: client)
    post = instance.post
    def callback(result):
        results.append(result)
        post(result)
    instance._consumer.callback = SimpleNamespace(post=callback)
    channel = Channel()
    instance._on_message(channel, SimpleNamespace(delivery_tag=1), None, b'{"operation":"invalid"}')
    assert results[0]["success"] is False
    assert len(results[0]["error"]["traceId"]) == 32
    assert len(requests) == 1
    assert requests[0].url == "http://kb/result"
    assert channel.acked == ([1] if response_status == 204 else [])
    assert channel.nacked == ([(1, True)] if response_status == 503 else [])
