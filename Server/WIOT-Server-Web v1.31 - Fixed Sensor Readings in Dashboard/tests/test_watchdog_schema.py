"""Additive wire schema and legacy-reader compatibility for IWDG diagnostics."""
import unittest
from pathlib import Path
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
import messages_pb2
from power_commands import power_metadata, power_dashboard_fields


class WatchdogSchemaTests(unittest.TestCase):
    def test_power_counter_is_additive_and_distinct(self):
        for cls, tag in ((messages_pb2.Status_Message, 36), (messages_pb2.Telemetry, 45)):
            self.assertEqual(cls.DESCRIPTOR.fields_by_name['power_reset_count'].number, tag)
            msg = cls(power_reset_count=4294967295, wdt_reset_count=17)
            restored = cls.FromString(msg.SerializeToString())
            self.assertEqual((restored.power_reset_count, restored.wdt_reset_count), (4294967295, 17))
            self.assertEqual(power_dashboard_fields(power_metadata(msg))['Power Resets'], 4294967295)
            self.assertEqual(cls.FromString(b'').power_reset_count, 0)
    def test_schema_copies_match(self):
        server = Path(__file__).resolve().parents[1]
        node = server.parents[1] / "Node/IoT_Node_Encrypted/src/generated/sensor.proto"
        self.assertEqual((server / "messages.proto").read_text(), (server / "sensor.proto").read_text())
        self.assertEqual(node.read_text(), (server / "messages.proto").read_text())

    def test_field_tags_and_wire_roundtrip(self):
        for cls, tag, prefix in ((messages_pb2.Status_Message, 35, b'\x98\x02'),
                                 (messages_pb2.Telemetry, 44, b'\xe0\x02')):
            with self.subTest(message=cls.__name__):
                self.assertEqual(cls.DESCRIPTOR.fields_by_name['wdt_reset_count'].number, tag)
                msg = cls(wdt_reset_count=1)
                self.assertEqual(msg.SerializeToString(), prefix + b'\x01')
                maximum = cls(wdt_reset_count=4294967295)
                self.assertEqual(cls.FromString(maximum.SerializeToString()).wdt_reset_count, 4294967295)
                self.assertEqual(cls.FromString(b'').wdt_reset_count, 0)
                self.assertEqual(power_dashboard_fields(power_metadata(msg))['WDT Resets'], 1)
        self.assertEqual(messages_pb2.Status_Message.DESCRIPTOR.fields_by_name['battery_voltage'].number, 19)
        self.assertEqual(messages_pb2.Telemetry.DESCRIPTOR.fields_by_name['command_ack_success'].number, 43)

    def test_old_reader_ignores_new_counter_without_losing_existing_fields(self):
        descriptor = descriptor_pb2.FileDescriptorProto.FromString(messages_pb2.DESCRIPTOR.serialized_pb)
        for message in descriptor.message_type:
            kept = [field for field in message.field if field.name not in ('wdt_reset_count', 'power_reset_count')]
            del message.field[:]
            message.field.extend(kept)
        pool = descriptor_pool.DescriptorPool()
        pool.Add(descriptor)
        for cls in (messages_pb2.Status_Message, messages_pb2.Telemetry):
            old_cls = message_factory.GetMessageClass(pool.FindMessageTypeByName(cls.DESCRIPTOR.full_name))
            msg = cls(node_id=35, battery_voltage=3.5, wdt_reset_count=27, power_reset_count=9)
            old_msg = old_cls.FromString(msg.SerializeToString())
            self.assertEqual(old_msg.node_id, 35)
            self.assertEqual(old_msg.battery_voltage, 3.5)
            self.assertNotIn('wdt_reset_count', old_msg.DESCRIPTOR.fields_by_name)
            self.assertNotIn('power_reset_count', old_msg.DESCRIPTOR.fields_by_name)


if __name__ == '__main__':
    unittest.main()
