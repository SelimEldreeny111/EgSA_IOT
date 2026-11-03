"""Host tests for the real diagnostics header plus a source coverage audit.

Usage: python run_tests.py --compiler /path/to/g++
No hardware, credentials or network connections are required.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--compiler',default='g++')
args=parser.parse_args()
here=Path(__file__).resolve().parent
node=here.parent.parent
env=os.environ.copy()
env['PATH']=str(Path(args.compiler).resolve().parent)+os.pathsep+env['PATH']
with tempfile.TemporaryDirectory(prefix='wiot-debug-') as temporary:
    for enabled,lite,raw in [(e,l,r) for e in (0,1) for l in (0,1) for r in (0,1)]:
        exe=Path(temporary)/f'log-{enabled}-{lite}-{raw}.exe'
        subprocess.run([args.compiler,'-std=c++14','-Wall','-Wextra','-Werror','-pedantic',
            '-Os','-ffunction-sections','-fdata-sections','-Wl,--gc-sections',
            '-DAPP_CONFIG_H',f'-DAPP_ENABLE_DEBUG={enabled}',f'-DAPP_DEBUG_LITE={lite}',f'-DAPP_DEBUG_RAW_FRAMES={raw}',
            '-I',str(here/'fakes'),str(here/'debug_log_test.cpp'),str(here/'other_module.cpp'),
            '-o',str(exe)],check=True,env=env)
        subprocess.run([str(exe)],check=True,env=env)
        if not enabled or lite:
            assert b'unique_debug_string_7f93a' not in exe.read_bytes(), 'lite/silent build retains full debug strings'
    transcripts=[]
    for enabled,lite in [(1,0),(1,1),(0,1)]:
        exe=Path(temporary)/f'lora-{enabled}-{lite}.exe'
        fixtures=here.parent/'flash_journal'
        subprocess.run([args.compiler,'-std=c++14','-Wall','-Wextra','-Werror','-pedantic',
            '-Os',f'-DAPP_ENABLE_DEBUG={enabled}',f'-DAPP_DEBUG_LITE={lite}','-DWIOT_TEST_WIRE_TRANSCRIPT',
            '-I',str(fixtures/'fakes'),'-include',str(fixtures/'fakes/LoraConfig.h'),
            str(fixtures/'lora_large_frame_test.cpp'),'-o',str(exe)],check=True,env=env)
        transcripts.append(subprocess.check_output([str(exe)],env=env))
    assert transcripts[0]==transcripts[1]==transcripts[2], 'debug policy changed LoRa wire bytes'
    assert b'wire_bytes=0' not in transcripts[0]
    print('PASS actual LoRa reassembly and fragment ACK wire bytes identical in full/lite/off modes')
    mqtt=here.parent/'mqtt_priority'
    for modem in ('SIM','WIFI'):
        for enabled,lite in [(1,0),(1,1),(0,1)]:
            exe=Path(temporary)/f'mqtt-{modem}-{enabled}-{lite}.exe'
            flags=['-DTEST_ESP8266'] if modem=='WIFI' else []
            subprocess.run([args.compiler,'-std=c++14','-Wall','-Wextra','-Werror','-pedantic',
                f'-DAPP_ENABLE_DEBUG={enabled}',f'-DAPP_DEBUG_LITE={lite}',*flags,
                '-I',str(mqtt/'fakes'),'-include',str(mqtt/'fakes/TestAppConfig.h'),
                str(node/'src/comm/MQTT.cpp'),str(mqtt/'mqtt_priority_test.cpp'),
                '-o',str(exe)],check=True,env=env)
            for case in ('command_priority','ack_retry','foreign_node','zero_write','receive_during_pending_send'):
                subprocess.run([str(exe),case],check=True,env=env,stdout=subprocess.DEVNULL)
    print('PASS 30 production MQTT command-priority/reply/failure scenarios across SIM/WiFi and full/lite/off')
    owned=[node/'IoT_Node_Encrypted.ino']+list((node/'src').rglob('*.cpp'))+list((node/'src').rglob('*.h'))
    for file in owned:
        if 'third_party' in file.parts or file.name=='DebugLog.h':
            continue
        assert not re.search(r'\bSerialMon\.(print\w*|write|begin|flush)\s*\(',file.read_text(encoding='utf-8-sig')),file
    print('PASS silent binary drops debug literals; all owned diagnostic outputs use the master switch')
