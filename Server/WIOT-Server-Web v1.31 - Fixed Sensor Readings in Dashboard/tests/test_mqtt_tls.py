"""Exercise Paho's TLS connection and existing wire envelope over loopback."""
import socket
import ssl
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mqtt_impl import MqttNodeClient

KEY = bytes(range(16))
TOPIC = 'wiot/Company_1/Region_1/2/status'


def packet(stream):
    header = stream.read(1)
    if not header:
        return None, b''
    length = shift = 0
    while True:
        digit = stream.read(1)[0]
        length |= (digit & 0x7f) << shift
        if digit < 128:
            break
        shift += 7
    return header[0] >> 4, stream.read(length)


class MqttTlsTests(unittest.TestCase):
    def setUp(self):
        # Earlier test classes may leave a file logger pointing into a deleted temp directory.
        logger = patch('mqtt_impl.logger')
        logger.start()
        self.addCleanup(logger.stop)

    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        folder = Path(temp.name)
        now = datetime.now(timezone.utc)
        root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        root = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'WIOT test CA')])
        leaf = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])

        def cert(subject, issuer, key):
            return (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer)
                    .public_key(key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1)))

        ca_cert = cert(root, root, root_key).add_extension(
            x509.BasicConstraints(ca=True, path_length=0), critical=True).add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, None, None),
            critical=True).add_extension(x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()),
                                         critical=False).sign(root_key, hashes.SHA256())
        server_cert = cert(leaf, root, leaf_key).add_extension(
            x509.SubjectAlternativeName([x509.DNSName('localhost')]), critical=False).add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()),
            critical=False).sign(root_key, hashes.SHA256())
        cls.ca = folder / 'ca.pem'
        cls.ca.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
        crt = folder / 'server.pem'
        crt.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
        key = folder / 'server.key'
        key.write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        cls.tls_broker = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.tls_broker.minimum_version = ssl.TLSVersion.TLSv1_2
        cls.tls_broker.maximum_version = ssl.TLSVersion.TLSv1_2
        cls.tls_broker.load_cert_chain(crt, key)

    def broker_session(self, peer, secured=True):
        with peer:
            peer.settimeout(4)
            try:
                connection = self.tls_broker.wrap_socket(peer, server_side=True) if secured else peer
            except (ssl.SSLError, ConnectionResetError):
                return None
            with connection, connection.makefile('rb') as stream:
                packet_type, connect = packet(stream)
                self.assertEqual(packet_type, 1)
                connection.sendall(b'\x20\x02\x00\x00')
                packet_type, subscribe = packet(stream)
                self.assertEqual(packet_type, 8)
                connection.sendall(b'\x90\x03' + subscribe[:2] + b'\x01')
                # Send a QoS 0 project payload after SUBACK.
                frame = MqttNodeClient.encrypt_frame_static(b'fixture', KEY)['payload']
                topic = TOPIC.encode()
                payload = len(topic).to_bytes(2, 'big') + topic + frame
                connection.sendall(bytes((0x30, len(payload))) + payload)
                while packet(stream)[0] not in (None, 14):
                    pass
                return connect

    def run_client(self, *, secured, use_tls, host, trust=None, failure=None):
        with socket.socket() as listener, ThreadPoolExecutor(max_workers=1) as worker:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            listener.settimeout(4)
            result = worker.submit(lambda: self.broker_session(listener.accept()[0], secured))
            received = threading.Event()
            on_plaintext = Mock(side_effect=lambda *args: received.set())
            client = MqttNodeClient(host, listener.getsockname()[1], KEY, 'tls-test', [TOPIC],
                on_plaintext=on_plaintext, use_tls=use_tls, ca_file=trust,
                username='bench-test' if use_tls else None, password='test-password' if use_tls else None)
            if failure:
                with self.assertRaises(failure):
                    client.connect(connect_timeout=3)
                self.assertFalse(client.is_connected())
                self.assertIsNone(result.result(timeout=4))
                on_plaintext.assert_not_called()
                return
            try:
                client.connect(connect_timeout=3)
                self.assertTrue(received.wait(4), 'No MQTT message after SUBACK')
                self.assertTrue(client.is_connected())
                on_plaintext.assert_called_once_with(TOPIC, b'fixture')
            finally:
                client.disconnect()
            return result.result(timeout=4)

    def test_tls12_connect_suback_and_encrypted_payload(self):
        connect = self.run_client(secured=True, use_tls=True, host='localhost', trust=str(self.ca))
        self.assertIn(b'bench-test', connect)
        self.assertIn(b'test-password', connect)

    def test_plain_mode_has_no_tls_or_credentials(self):
        connect = self.run_client(secured=False, use_tls=False, host='localhost')
        self.assertNotIn(b'test-password', connect)
        with self.assertRaisesRegex(ValueError, 'require TLS'):
            MqttNodeClient('localhost', 1883, KEY, 'plain-test', [], username='bench-test')

    def test_tls_rejects_wrong_hostname(self):
        self.run_client(secured=True, use_tls=True, host='127.0.0.1', trust=str(self.ca),
                        failure=ssl.SSLCertVerificationError)

    def test_tls_rejects_untrusted_ca(self):
        self.run_client(secured=True, use_tls=True, host='localhost',
                        failure=ssl.SSLCertVerificationError)


if __name__ == '__main__':
    unittest.main()
