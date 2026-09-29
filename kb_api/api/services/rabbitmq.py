from __future__ import annotations

import json

import pika

INDEX_TASK_QUEUE = "kb.index.tasks"


class RabbitMQClient:
    def __init__(self, url: str):
        self.url = url

    def _new_connection(self):
        return pika.BlockingConnection(pika.URLParameters(self.url))

    def publish(self, queue_name: str, message: dict) -> None:
        with self._new_connection() as connection:
            channel = connection.channel()
            channel.queue_declare(queue=queue_name, durable=True)
            channel.basic_publish(
                exchange="",
                routing_key=queue_name,
                body=json.dumps(message, separators=(",", ":")).encode(),
                properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
            )

    def close(self) -> None:
        pass
