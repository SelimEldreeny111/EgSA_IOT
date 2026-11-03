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
    for enabled,raw in [(1,0),(1,1),(0,0),(0,1)]:
        exe=Path(temporary)/f'log-{enabled}-{raw}.exe'
        subprocess.run([args.compiler,'-std=c++14','-Wall','-Wextra','-Werror','-pedantic',
            '-Os','-ffunction-sections','-fdata-sections','-Wl,--gc-sections',
            '-DAPP_CONFIG_H',f'-DAPP_ENABLE_DEBUG={enabled}',f'-DAPP_DEBUG_RAW_FRAMES={raw}',
            '-I',str(here/'fakes'),str(here/'debug_log_test.cpp'),str(here/'other_module.cpp'),
            '-o',str(exe)],check=True,env=env)
        subprocess.run([str(exe)],check=True,env=env)
        if not enabled:
            assert b'unique_debug_string_7f93a' not in exe.read_bytes(), 'disabled build retains debug strings'
    transcripts=[]
    for enabled in (1,0):
        exe=Path(temporary)/f'lora-{enabled}.exe'
        fixtures=here.parent/'flash_journal'
        subprocess.run([args.compiler,'-std=c++14','-Wall','-Wextra','-Werror','-pedantic',
            '-Os',f'-DAPP_ENABLE_DEBUG={enabled}','-DWIOT_TEST_WIRE_TRANSCRIPT',
            '-I',str(fixtures/'fakes'),'-include',str(fixtures/'fakes/LoraConfig.h'),
            str(fixtures/'lora_large_frame_test.cpp'),'-o',str(exe)],check=True,env=env)
        transcripts.append(subprocess.check_output([str(exe)],env=env))
    assert transcripts[0]==transcripts[1], 'debug policy changed LoRa wire bytes'
    assert b'wire_bytes=0' not in transcripts[0]
    print('PASS actual LoRa reassembly and fragment ACK wire bytes identical with debug on/off')
    owned=[node/'IoT_Node_Encrypted.ino']+list((node/'src').rglob('*.cpp'))+list((node/'src').rglob('*.h'))
    for file in owned:
        if 'third_party' in file.parts or file.name=='DebugLog.h':
            continue
        assert not re.search(r'\bSerialMon\.(print\w*|write|begin|flush)\s*\(',file.read_text(encoding='utf-8-sig')),file
    print('PASS silent binary drops debug literals; all owned diagnostic outputs use the master switch')
