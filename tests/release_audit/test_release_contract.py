"""Read-only cross-component release checks; never loads deployment secrets."""
from pathlib import Path
import importlib.util
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
NODE = ROOT / "Node/IoT_Node_Encrypted"
SERVER = ROOT / "Server/WIOT-Server-Web v1.31 - Fixed Sensor Readings in Dashboard"
spec = importlib.util.spec_from_file_location("release_messages_pb2", SERVER / "messages_pb2.py")
messages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(messages)


def schema(path):
    text = re.sub(r"//[^\n]*", "", path.read_text(encoding="utf-8"))
    return {
        name: {field: (kind, int(tag)) for kind, field, tag in
               re.findall(r"(\w+)\s+(\w+)\s*=\s*(\d+)\s*;", body)}
        for name, body in re.findall(r"message\s+(\w+)\s*\{([^}]+)\}", text)
    }


class ReleaseContractTests(unittest.TestCase):
    def test_fresh_clone_topic_template_matches_case_sensitive_server_routes(self):
        import subprocess
        import tempfile
        text = (NODE / "src/config/AppConfig.cpp.example").read_text(encoding="utf-8")
        config = (NODE / "src/config/AppConfig.h").read_text(encoding="utf-8")
        macros = config[config.index('// Public routing identity.'):config.index('constexpr uint16_t kNodeId')]
        declarations = '\n'.join(re.findall(r'const char kMqtt\w+\[\] = [^;]+;', text))
        declarations = '\n'.join(line for line in declarations.splitlines() if 'kMqttServer' not in line)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'topic_contract.cpp'; exe = Path(directory)/'topic_contract.exe'
            source.write_text('#include <iostream>\n#include "MqttTopicRouting.h"\n#define APP_NODE_ID 3\n#define APP_MQTT_REGION "Region_2"\n' +
                macros + declarations + '\nint main(){ std::cout << kMqttPublishTopicStatus << "\\n" << '
                'kMqttPublishTopicTlm << "\\n" << kMqttCommandTopic << "\\n" << kMqttBroadcastTopic << "\\n" << '
                'kMqttGatewayCommandWildcardTopic << "\\n" << kMqttClientId; }',encoding='utf-8')
            subprocess.run(['g++','-std=c++14','-I',str(NODE/'src/comm'),str(source),'-o',str(exe)],check=True,capture_output=True)
            self.assertEqual(subprocess.check_output([str(exe)],text=True).splitlines(),[
                'wiot/Company_1/Region_2/3/status','wiot/Company_1/Region_2/3/data',
                'wiot/Company_1/Region_2/3/cmd','wiot/Company_1/Region_2/broadcast',
                'wiot/Company_1/Region_2/+/cmd','wiot-Company_1-Region_2-3'])

    def test_all_three_proto_sources_match(self):
        expected = schema(NODE / "src/generated/sensor.proto")
        self.assertEqual(set(expected), {"FlowReading", "Status_Message", "Telemetry", "CMD_Message"})
        for filename in ("sensor.proto", "messages.proto"):
            with self.subTest(filename=filename):
                self.assertEqual(expected, schema(SERVER / filename))

    def test_python_generated_descriptor_matches_every_node_field(self):
        kinds = {"float": 2, "uint64": 4, "bool": 8, "uint32": 13, "sint64": 18}
        for name, fields in schema(NODE / "src/generated/sensor.proto").items():
            descriptor = getattr(messages, name).DESCRIPTOR
            self.assertEqual(set(fields), set(descriptor.fields_by_name))
            for field, (kind, tag) in fields.items():
                with self.subTest(message=name, field=field):
                    actual = descriptor.fields_by_name[field]
                    self.assertEqual(tag, actual.number)
                    if kind in kinds:
                        self.assertEqual(kinds[kind], actual.type)
                    else:
                        self.assertEqual(kind, actual.message_type.name)

    def test_nanopb_generated_tags_match_every_source_field(self):
        header = (NODE / "src/generated/sensor.pb.h").read_text(encoding="utf-8")
        tags = dict(re.findall(r"#define\s+(\w+)_tag\s+(\d+)", header))
        for name, fields in schema(NODE / "src/generated/sensor.proto").items():
            for field, (_, tag) in fields.items():
                with self.subTest(message=name, field=field):
                    self.assertEqual(tag, int(tags[f"{name}_{field}"]))

    def test_four_sensor_voltage_power_ack_and_counter_fields_are_present(self):
        status = messages.Status_Message.DESCRIPTOR.fields_by_name
        telemetry = messages.Telemetry.DESCRIPTOR.fields_by_name
        for fields in (status, telemetry):
            for field in ("soil_temperature", "soil_moisture", "ec_temperature",
                          "ec_moisture", "electrical_conductivity", "sensor_mask",
                          "active_sensor_count", "secondary_flow_meter", "rtc_valid",
                          "flow_period_quality", "battery_voltage", "power_mode",
                          "power_state", "wake_remaining_seconds", "wdt_reset_count"):
                self.assertIn(field, fields)
        self.assertEqual(status["wdt_reset_count"].number, 35)
        self.assertEqual(telemetry["wdt_reset_count"].number, 44)
        for field in ("wake_command_ack", "wake_request_id", "command_ack_request_id",
                      "command_ack_cmd_id", "command_ack_success"):
            self.assertIn(field, telemetry)

    def test_required_release_sources_and_templates_exist(self):
        paths = ["README.md", "RELEASE_GUIDE.md", "Validate-Release.ps1",
                 "Node/IoT_Node_Encrypted/Doxyfile", "Node/IoT_Node_Encrypted/generate_doxygen.ps1",
                 "Node/IoT_Node_Encrypted/src/config/AppConfig.cpp.example",
                 "Node/IoT_Node_Encrypted/src/config/AppSecrets.example.h"]
        paths += [f"Node/IoT_Node_Encrypted/src/devices/{sensor}Sensor.cpp"
                  for sensor in ("Tuf", "Supmea", "Hnda", "Sondas")]
        paths += [f"SENSORS/{folder}/{filename}" for folder, filename in (
            ("Multi Sensor RS485 Simulator", "multi_sensor_simulator.py"),
            ("Multi Sensor RS485 Simulator", "build_exe.ps1"),
            ("TUF2000B Flow meter/simulator", "tuf2000b_simulator.py"),
            ("Supmea Flow meter/simulator", "supmea_fmc240_simulator.py"),
            ("Supmea Flow meter/simulator", "build_exe.ps1"))]
        for filename in ("server_web.py", "command_queue.py", "node_config.example.json", ".env.example"):
            self.assertTrue((SERVER / filename).is_file(), filename)
        for path in paths:
            self.assertTrue((ROOT / path).is_file(), path)


if __name__ == "__main__":
    unittest.main()
