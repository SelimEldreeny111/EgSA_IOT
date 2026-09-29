"""
mqtt_impl.py
============
Annotated MQTT transport + AES-CBC/PKCS7 framing layer.

Purpose of this file:
- Own the MQTT client connection.
- Encrypt outgoing protobuf bytes into the project's MQTT wire format.
- Decrypt incoming MQTT payloads back into plaintext protobuf bytes.
- Expose status/debug callbacks used by the GUI log panes.

Wire format used by this project:
    [1 byte code version] [16 bytes random IV] [ciphertext]

Where ciphertext = AES-CBC( PKCS7( protobuf_bytes ) )

Main integration points:
- paho-mqtt handles broker transport.
- cryptography handles AES-CBC and PKCS7.
- messages_pb2 is only used here for optional RX debug parsing/logging.
"""

import os
import threading
import logging
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

import paho.mqtt.client as mqtt
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
import messages_pb2

BLOCK_SIZE = 16
logger = logging.getLogger(__name__)

CMD_NAMES = {
    0: "NA",
    1: "SRATE",
    2: "STRAN",
    3: "STIME",
    4: "GOSTM",
    5: "VALVE",
    6: "WAKE",
}


@dataclass
class Counters:
    """Simple TX/RX counters displayed in logs; incremented under a lock."""

    tx_counter: int = 0
    rx_counter: int = 0

    def inc_tx(self):
        self.tx_counter += 1
        return self.tx_counter

    def inc_rx(self):
        self.rx_counter += 1
        return self.rx_counter


class MqttNodeClient:
    """
    Project wrapper around paho-mqtt plus AES framing.
    - Encrypt outgoing protobuf bytes into the project's MQTT wire format.
    - Decrypt incoming MQTT payloads back into plaintext protobuf bytes.
    - Expose status/debug callbacks used by the GUI log panes.
    """

    FRAME_VERSION = b'\x01'

    def __init__(
        self,
        broker_host: str,
        broker_port: int,
        aes_key_16: bytes,
        client_id: str,
        subscribe_topics: List[str],
        on_plaintext: Optional[Callable[[str, bytes], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        debug: bool = True,
    ):
        # Broker / framing settings injected from the GUI.
        self.broker_host = broker_host
        self.broker_port = int(broker_port)
        self.aes_key_16 = aes_key_16
        self.subscribe_topics = subscribe_topics
        self.on_plaintext = on_plaintext
        self.on_status = on_status
        self.debug = debug

        # Lock is used because MQTT callbacks and GUI actions may touch counters concurrently.
        self._lock = threading.Lock()
        self.counters = Counters()
        self.connected = False

        # Underlying paho-mqtt client and its callback wiring.
        self.client = mqtt.Client(client_id=client_id)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    @staticmethod
    def _pad_pkcs7(data: bytes) -> tuple[bytes, int]:
        """Pad plaintext to a multiple of 16 bytes and also return pad length."""
        padder = padding.PKCS7(BLOCK_SIZE * 8).padder()
        padded = padder.update(data) + padder.finalize()
        return padded, len(padded) - len(data)

    @staticmethod
    def _unpad_pkcs7(data: bytes) -> bytes:
        """Remove PKCS7 padding after AES decryption."""
        unpadder = padding.PKCS7(BLOCK_SIZE * 8).unpadder()
        return unpadder.update(data) + unpadder.finalize()

    def _encrypt_cbc(self, plaintext: bytes):
        """
        Encrypt one plaintext protobuf payload with AES-CBC.

        Sensitive block:
        - Plaintext is padded first.
        - A fresh random IV is generated for each frame.
        - Returned metadata is later displayed in the GUI logs.
        """
        padded, pad_len = self._pad_pkcs7(plaintext)

        # Non-obvious but important: random IV per frame improves CBC usage.
        iv = os.urandom(BLOCK_SIZE)

        cipher = Cipher(algorithms.AES(self.aes_key_16), modes.CBC(iv), backend=default_backend())
        enc = cipher.encryptor()
        ciphertext = enc.update(padded) + enc.finalize()
        return iv, ciphertext, len(padded), pad_len

    def _decrypt_cbc_meta(self, ciphertext: bytes, iv: bytes):
        """Decrypt ciphertext with the provided IV and report padded/plain lengths."""
        cipher = Cipher(algorithms.AES(self.aes_key_16), modes.CBC(iv), backend=default_backend())
        dec = cipher.decryptor()
        padded = dec.update(ciphertext) + dec.finalize()
        try:
            plain = self._unpad_pkcs7(padded)
            pad_len = len(padded) - len(plain)
        except ValueError as e:
            # Fallback for firmware using Zero Padding
            if b"\x00" in padded and padded[-1] == 0:
                plain = padded.rstrip(b"\x00")
                pad_len = len(padded) - len(plain)
            else:
                raise ValueError(f"Padding error. Decrypted hex: {padded.hex(' ')}") from e
        return plain, len(padded), pad_len

    @classmethod
    def encrypt_frame_static(
        cls,
        plaintext: bytes,
        aes_key_16: bytes,
        iv: bytes | None = None,
    ):
        """
        Build one full MQTT payload frame without touching instance state.

        Used by the GUI error-injection tools to produce frames that intentionally
        use an alternate key, code version, or IV while leaving the connected
        MQTT session configuration unchanged.
        """
        if len(aes_key_16) != BLOCK_SIZE:
            raise ValueError("AES key must be 16 bytes (32 hex chars).")
        if iv is None:
            iv = os.urandom(BLOCK_SIZE)
        if len(iv) != BLOCK_SIZE:
            raise ValueError("IV must be exactly 16 bytes.")

        padder = padding.PKCS7(BLOCK_SIZE * 8).padder()
        padded = padder.update(plaintext) + padder.finalize()
        pad_len = len(padded) - len(plaintext)

        cipher = Cipher(algorithms.AES(aes_key_16), modes.CBC(iv), backend=default_backend())
        enc = cipher.encryptor()
        ciphertext = enc.update(padded) + enc.finalize()

        payload = cls.FRAME_VERSION + iv + ciphertext
        return {
            "payload": payload,
            "ciphertext": ciphertext,
            "code_version": cls.FRAME_VERSION.hex(),
            "iv_hex": iv.hex(),
            "frame_len": len(payload),
            "cipher_len": len(ciphertext),
            "padded_len": len(padded),
            "pad_len": pad_len,
            "proto_len": len(plaintext),
        }

    def encrypt_frame(self, plaintext: bytes):
        """
        Build one full MQTT payload frame.

        Returned dict contains both the actual payload and metadata used by the GUI.
        """
        frame = self.encrypt_frame_static(
            plaintext=plaintext,
            aes_key_16=self.aes_key_16,
        )

        # Counter increment is guarded because callbacks may run from MQTT network thread.
        with self._lock:
            tx = self.counters.inc_tx()

        frame["tx_counter"] = tx
        return frame

    def publish_plaintext(self, topic: str, plaintext: bytes, qos: int = 1):
        """
        Encrypt plaintext bytes, publish them through MQTT, and return frame metadata.

        Even though the method name says plaintext, the sent MQTT payload is encrypted.
        The name reflects the input to this method, not the wire format.
        """
        frame = self.encrypt_frame(plaintext)
        if self.on_status:
            self.on_status(f"[TX#{frame['tx_counter']}] RAW MQTT TX topic={topic} len={frame['frame_len']}")
            self.on_status(f"MQTT outgoing frame bytes: {frame['payload'].hex(' ')}")
            self.on_status("")
        result = self.client.publish(topic, frame["payload"], qos=qos, retain=False)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish rejected (rc={result.rc})")
        return frame

    def publish_raw(self, topic: str, payload: bytes, qos: int = 1, note: str = "raw"):
        """
        Publish already-assembled bytes without applying encryption or validation.

        This is intentionally low-level and is used by the GUI error-injection
        section to send malformed MQTT payloads for negative testing.
        """
        with self._lock:
            tx = self.counters.inc_tx()

        if self.on_status:
            self.on_status(f"[TX#{tx}] RAW MQTT TX topic={topic} len={len(payload)} (note={note})")
            self.on_status(f"MQTT outgoing frame bytes: {payload.hex(' ')}")
            self.on_status("")

        self.client.publish(topic, payload, qos=qos)
        return {
            "payload": payload,
            "tx_counter": tx,
            "frame_len": len(payload),
            "note": note,
        }

    def decrypt_frame_meta(self, payload: bytes):
        """
        Decrypt one incoming MQTT payload.

        Expected wire format only:
        [1-byte code_version][16-byte iv][ciphertext]
        """
        if len(payload) < 17:
            raise ValueError(f"invalid framed payload length: {len(payload)}")

        code_ver = payload[:1]
        if code_ver != self.FRAME_VERSION:
            raise ValueError(f"Invalid frame version: received 0x{code_ver.hex()}, expected 0x{self.FRAME_VERSION.hex()}")

        iv = payload[1:17]
        ciphertext = payload[17:]

        if len(ciphertext) == 0 or len(ciphertext) % 16 != 0:
            raise ValueError(f"invalid ciphertext length: {len(ciphertext)}")

        plain, dec_len, pad_len = self._decrypt_cbc_meta(ciphertext, iv)
        return plain, dec_len, pad_len, code_ver.hex(), iv.hex(), len(ciphertext)

    def connect(self, keepalive=60, connect_timeout=10):
        """Connect to broker with timeout and start the background network loop."""
        try:
            logger.info(f"[MQTT] Attempting connection to {self.broker_host}:{self.broker_port} with timeout={connect_timeout}s")
            if self.on_status:
                self.on_status(f"[MQTT] Attempting connection to {self.broker_host}:{self.broker_port}...")
            
            # Set socket timeout to prevent indefinite hangs
            self.client.socket_keepalive_options = None
            self.client._sock_connect_timeout = connect_timeout
            
            # Attempt connection
            self.client.connect(self.broker_host, self.broker_port, keepalive)
            
            # Start network loop
            self.client.loop_start()
            
            logger.info(f"[MQTT] Connection initiated (waiting for _on_connect callback)")
            if self.on_status:
                self.on_status(f"[MQTT] Connection initiated, waiting for broker response...")
        except OSError as e:
            error_msg = f"[MQTT] Connection failed (OS error): {e}"
            logger.error(error_msg)
            if self.on_status:
                self.on_status(error_msg)
            self.connected = False
            raise
        except Exception as e:
            error_msg = f"[MQTT] Connection failed: {type(e).__name__}: {e}"
            logger.error(error_msg)
            if self.on_status:
                self.on_status(error_msg)
            self.connected = False
            raise

    def disconnect(self):
        """Stop background loop first, then disconnect cleanly from the broker."""
        if self.client.is_connected():
            self.client.disconnect()
        self.client.loop_stop()
        self.connected = False

    def is_connected(self):
        return self.connected and self.client.is_connected()

    def _on_connect(self, client, userdata, flags, rc):
        """paho-mqtt callback fired after broker connection completes."""
        self.connected = (rc == 0)
        
        # Map MQTT return codes to human-readable messages
        rc_messages = {
            0: "Success",
            1: "Connection refused - incorrect protocol version",
            2: "Connection refused - invalid client identifier",
            3: "Connection refused - server unavailable",
            4: "Connection refused - bad username or password",
            5: "Connection refused - not authorized",
        }
        rc_msg = rc_messages.get(rc, f"Unknown error code {rc}")
        
        if rc == 0:
            logger.info(f"[MQTT] Successfully connected to broker")
            if self.on_status:
                self.on_status(f"[MQTT] Connected rc={rc} ({rc_msg})")
        else:
            logger.error(f"[MQTT] Connection failed with rc={rc}: {rc_msg}")
            if self.on_status:
                self.on_status(f"[MQTT] Connection FAILED rc={rc}: {rc_msg}")
            return

        # Subscribe to topics
        sub_count = 0
        for t in self.subscribe_topics:
            if not t:
                continue
            try:
                result, mid = client.subscribe(t, qos=1)
                logger.info(f"[MQTT] Subscribed to: {t} (result={result}, mid={mid})")
                if self.on_status:
                    self.on_status(f"[MQTT] Subscribed to: {t}")
                sub_count += 1
            except Exception as e:
                logger.error(f"[MQTT] Failed to subscribe to {t}: {e}")
                if self.on_status:
                    self.on_status(f"[MQTT] ERROR subscribing to {t}: {e}")
        
        logger.info(f"[MQTT] Subscription complete - {sub_count}/{len(self.subscribe_topics)} topics")
        if self.on_status:
            self.on_status(f"[MQTT] Ready - subscribed to {sub_count} topics")

    def _on_disconnect(self, client, userdata, rc):
        """paho-mqtt callback fired when broker connection is closed."""
        self.connected = False
        
        if rc == 0:
            logger.info(f"[MQTT] Disconnected cleanly from broker")
            if self.on_status:
                self.on_status(f"[MQTT] Disconnected rc={rc} (clean)")
        else:
            logger.warning(f"[MQTT] Unexpected disconnection from broker - rc={rc}")
            if self.on_status:
                self.on_status(f"[MQTT] Disconnected UNEXPECTEDLY rc={rc}")

    def _on_message(self, client, userdata, msg):
        """
        paho-mqtt callback for inbound payloads.

        Guaranteed behavior:
        - raw topic/payload are logged first
        - decrypt/parse details are logged next if successful
        - decrypt errors are also logged to RX
        """
        raw = msg.payload

        with self._lock:
            rx = self.counters.inc_rx()

        if self.on_status:
            self.on_status(f"[RX#{rx}] RAW MQTT RX topic={msg.topic} len={len(raw)}")
            self.on_status(f"MQTT frame bytes: {raw.hex(' ')}")

        if not self.connected:
            if self.on_status:
                self.on_status(f"[RX#{rx}] Ignored MQTT payload because client is disconnected")
                self.on_status("")
            return

        try:
            plain, dec_len, pad_len, code_ver_hex, iv_hex, cipher_len = self.decrypt_frame_meta(raw)

            cmd_info = ""
            is_cmd_topic = msg.topic.lower().endswith("/cmd")
            if is_cmd_topic:
                try:
                    cmd = messages_pb2.CMD_Message()
                    cmd.ParseFromString(plain)
                    cmd_name = CMD_NAMES.get(cmd.cmd_id, "UNKNOWN")
                    cmd_info = f" node={cmd.node_id} cmd={cmd.cmd_id}({cmd_name}) data={cmd.cmd_data}"
                except Exception:
                    pass

            if self.on_status:
                warn = ""
                if is_cmd_topic and len(plain) != 16 and cmd_info:
                    warn = " WARN_proto_len!=16"
                self.on_status(
                    f"[RX#{rx}] code_ver={code_ver_hex} iv={iv_hex} cipher_len={cipher_len} dec_len={dec_len} pad_len={pad_len} proto_len={len(plain)}{cmd_info}{warn}"
                )
                self.on_status(f"Frame header: code_ver={code_ver_hex} iv={iv_hex}")

            if self.on_plaintext:
                self.on_plaintext(msg.topic, plain)

            if self.on_status:
                self.on_status("")
                
        except ValueError as e:
            error_msg = f"[RX#{rx}][ERROR] topic={msg.topic} - Decryption/padding error: {e}"
            logger.error(error_msg)
            if self.on_status:
                self.on_status(f"[RX#{rx}][ERROR] Decryption failed - wrong AES key?")
                self.on_status(f"Details: {str(e)[:100]}")
                self.on_status("")
        except Exception as e:
            error_msg = f"[RX#{rx}][ERROR] topic={msg.topic} - Unexpected error: {type(e).__name__}: {e}"
            logger.exception(error_msg)
            if self.on_status:
                self.on_status(f"[RX#{rx}][ERROR] {type(e).__name__}: {e}")
                self.on_status("")
