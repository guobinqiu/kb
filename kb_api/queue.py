from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Protocol

INDEX_TASK_QUEUE = "kb.index.tasks"


class QueueClient(Protocol):
    def publish(self, queue_name: str, message: dict) -> None: ...
    def start_consumer(self, queue_name: str, callback: Callable[[dict], None]) -> None: ...
    def close(self) -> None: ...


class RabbitMQClient:
    def __init__(self, url: str):
        self.url = url
        self._connection = None
        self._thread: threading.Thread | None = None

    def _new_connection(self):
        import pika

        return pika.BlockingConnection(pika.URLParameters(self.url))

    def publish(self, queue_name: str, message: dict) -> None:
        import pika

        with self._new_connection() as connection:
            channel = connection.channel()
            channel.queue_declare(queue=queue_name, durable=True)
            channel.basic_publish(
                exchange="",
                routing_key=queue_name,
                body=json.dumps(message, separators=(",", ":")).encode(),
                properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
            )

    def start_consumer(self, queue_name: str, callback: Callable[[dict], None]) -> None:
        def consume() -> None:
            connection = self._new_connection()
            self._connection = connection
            channel = connection.channel()
            channel.queue_declare(queue=queue_name, durable=True)

            def receive(ch, method, _properties, body) -> None:
                try:
                    message = json.loads(body)
                    if not isinstance(message, dict):
                        raise ValueError("queue message must be an object")
                    callback(message)
                except Exception:
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                else:
                    ch.basic_ack(delivery_tag=method.delivery_tag)

            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=queue_name, on_message_callback=receive, auto_ack=False)
            channel.start_consuming()

        self._thread = threading.Thread(target=consume, name="kb-queue-consumer", daemon=True)
        self._thread.start()

    def close(self) -> None:
        connection = self._connection
        if connection and connection.is_open:
            connection.add_callback_threadsafe(connection.close)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
