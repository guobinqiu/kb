from __future__ import annotations

import json
import logging
import time

import httpx

from kb_api.rag_indexer.index_tasks import IndexTaskConsumer
import pika


logger = logging.getLogger("rag_indexer")


class RabbitIndexWorker:
    def __init__(
        self, state, url: str, *, task_queue: str, callback_url: str,
        service_api_key: str, callback_timeout: float = 10.0,
    ):
        self.state = state
        self.url = url
        self.task_queue = task_queue
        self.callback_url = callback_url
        self.service_api_key = service_api_key
        self.callback_timeout = callback_timeout
        self._channel = None
        self._stopped = False
        self._consumer = IndexTaskConsumer(state, self)

    def stop(self) -> None:
        self._stopped = True

    def post(self, value: dict) -> None:
        with httpx.Client(timeout=self.callback_timeout) as client:
            response = client.post(
                self.callback_url,
                json=value,
                headers={"X-Service-Api-Key": self.service_api_key},
            )
            response.raise_for_status()

    def run(self) -> None:
        while not self._stopped:
            connection = None
            try:
                connection = pika.BlockingConnection(pika.URLParameters(self.url))
                self._channel = connection.channel()
                self._channel.queue_declare(queue=self.task_queue, durable=True)
                self._channel.basic_qos(prefetch_count=1)
                self._channel.basic_consume(queue=self.task_queue, on_message_callback=self._on_message)
                while not self._stopped and connection.is_open:
                    connection.process_data_events(time_limit=1)
            except Exception as exc:
                if not self._stopped:
                    logger.exception("RabbitMQ index worker failed", extra={"event": "index_worker_failed", "error": str(exc)})
                    time.sleep(2)
            finally:
                self._channel = None
                if connection is not None and connection.is_open:
                    connection.close()

    def _on_message(self, channel, method, _properties, body: bytes) -> None:
        try:
            self._consumer.handle(json.loads(body))
        except Exception:
            logger.exception("Index task delivery failed", extra={"event": "index_task_delivery_failed"})
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            time.sleep(1)
            return
        channel.basic_ack(delivery_tag=method.delivery_tag)
