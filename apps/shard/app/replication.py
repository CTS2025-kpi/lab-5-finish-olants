from __future__ import annotations

import json
import os
import queue
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple
import queue as py_queue

import pika


class Replicator:
    """
    Thread-safe Replicator:
      - Publisher: ONE dedicated thread owns pika connection/channel and publishes sequentially.
      - Consumer: separate thread with its own connection/channel.
    """

    def __init__(self, apply_event: Callable[[Dict[str, Any]], None]):
        self.apply_event = apply_event
        self.url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
        self.queue_name = os.getenv("RABBITMQ_QUEUE", "shard-events")
        self.publish_timeout = float(os.getenv("RABBITMQ_PUBLISH_TIMEOUT", "5"))
        self.reconnect_backoff = float(os.getenv("RABBITMQ_RECONNECT_BACKOFF", "1.0"))

        # publisher queue: (event, done_event, result_box)
        self._pub_q: "queue.Queue[Tuple[Dict[str, Any], threading.Event, dict]]" = queue.Queue()
        self._pub_thread: Optional[threading.Thread] = None

        # consumer thread
        self._cons_thread: Optional[threading.Thread] = None

    # -------------------- PUBLIC API --------------------
    def start_publisher_thread(self) -> None:
        if self._pub_thread and self._pub_thread.is_alive():
            return
        self._pub_thread = threading.Thread(target=self._publisher_loop, daemon=True)
        self._pub_thread.start()

    def start_consumer_thread(self) -> None:
        if self._cons_thread and self._cons_thread.is_alive():
            return
        self._cons_thread = threading.Thread(target=self._consume_forever, daemon=True)
        self._cons_thread.start()

    def publish(self, ev: Dict[str, Any]) -> None:
        """
        Safe to call from any thread (FastAPI request threads).
        Blocks until published or fails (so leader can return 503).
        """
        done = threading.Event()
        box: dict = {}
        self._pub_q.put((ev, done, box))

        if not done.wait(self.publish_timeout):
            raise TimeoutError(f"Publish timed out after {self.publish_timeout}s")

        if "exc" in box:
            raise box["exc"]

    # -------------------- PUBLISHER THREAD --------------------
    def _publisher_loop(self) -> None:
        conn: Optional[pika.BlockingConnection] = None
        ch: Optional[pika.channel.Channel] = None

        PUBLISH_RETRIES = int(os.getenv("RABBITMQ_PUBLISH_RETRIES", "5"))
        TICK_SEC = float(os.getenv("RABBITMQ_TICK_SEC", "1.0"))

        def connect() -> None:
            nonlocal conn, ch
            params = pika.URLParameters(self.url)
            params.heartbeat = int(os.getenv("RABBITMQ_HEARTBEAT", "30"))
            params.blocked_connection_timeout = int(os.getenv("RABBITMQ_BLOCKED_TIMEOUT", "30"))
            params.connection_attempts = int(os.getenv("RABBITMQ_CONN_ATTEMPTS", "3"))
            params.retry_delay = int(os.getenv("RABBITMQ_RETRY_DELAY", "2"))
            params.socket_timeout = float(os.getenv("RABBITMQ_SOCKET_TIMEOUT", "5"))

            conn = pika.BlockingConnection(params)
            ch = conn.channel()
            ch.queue_declare(queue=self.queue_name, durable=True)

            # makes publisher wait for broker confirm at protocol level
            ch.confirm_delivery()

        def close() -> None:
            nonlocal conn, ch
            try:
                if ch and ch.is_open:
                    ch.close()
            except Exception:
                pass
            try:
                if conn and conn.is_open:
                    conn.close()
            except Exception:
                pass
            ch = None
            conn = None

        while True:
            # --- keepalive tick: service heartbeats even if idle ---
            try:
                ev, done, box = self._pub_q.get(timeout=TICK_SEC)
            except py_queue.Empty:
                try:
                    if conn and conn.is_open:
                        conn.process_data_events(time_limit=0)
                except Exception:
                    close()
                continue

            body = json.dumps(ev).encode("utf-8")
            props = pika.BasicProperties(delivery_mode=2)

            last_exc: Optional[Exception] = None
            try:
                for _ in range(PUBLISH_RETRIES):
                    try:
                        if conn is None or conn.is_closed or ch is None or ch.is_closed:
                            connect()

                        assert ch is not None
                        ok = ch.basic_publish(
                            exchange="",
                            routing_key=self.queue_name,
                            body=body,
                            properties=props,
                            mandatory=False,
                        )

                        # With confirm_delivery(), ok is boolean (True on ack)
                        if ok is False:
                            raise RuntimeError("Publish was not confirmed by broker")

                        box["ok"] = True
                        last_exc = None
                        break
                    except Exception as e:
                        last_exc = e
                        close()
                        time.sleep(self.reconnect_backoff)

                if last_exc is not None:
                    box["exc"] = last_exc
            finally:
                done.set()

    # -------------------- CONSUMER THREAD --------------------
    def _consume_forever(self) -> None:
        while True:
            try:
                self._consume_once()
            except Exception:
                time.sleep(self.reconnect_backoff)

    def _consume_once(self) -> None:
        params = pika.URLParameters(self.url)
        params.heartbeat = int(os.getenv("RABBITMQ_HEARTBEAT", "30"))
        params.blocked_connection_timeout = int(os.getenv("RABBITMQ_BLOCKED_TIMEOUT", "30"))

        conn = pika.BlockingConnection(params)
        ch = conn.channel()
        ch.queue_declare(queue=self.queue_name, durable=True)
        ch.basic_qos(prefetch_count=50)

        def on_msg(channel, method, properties, body: bytes):
            ev = json.loads(body.decode("utf-8"))
            self.apply_event(ev)
            channel.basic_ack(delivery_tag=method.delivery_tag)

        ch.basic_consume(queue=self.queue_name, on_message_callback=on_msg, auto_ack=False)
        ch.start_consuming()
