"""Regenerate Arduino nanopb and matching server Python schemas from sensor.proto.

Requirements: protoc 33.5 and nanopb 0.4.9.1 (Python environment). No credentials.
Example: python regenerate_protocol.py --protoc C:/protoc-33.5-win64/bin/protoc.exe
"""
import argparse
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protoc',default='protoc')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    generated=root/'Node/IoT_Node_Encrypted/src/generated'
    server=root/'Server/WIOT-Server-Web v1.31 - Fixed Sensor Readings in Dashboard'
    spec=importlib.util.find_spec('nanopb')
    if spec is None:
        raise SystemExit('Install nanopb==0.4.9.1 in this Python environment first')
    generator=Path(spec.origin).parent/'generator/nanopb_generator.py'
    with tempfile.TemporaryDirectory(prefix='wiot-protocol-') as folder:
        descriptor=Path(folder)/'sensor.pb'
        subprocess.run([args.protoc,'-I',str(generated),'--descriptor_set_out='+str(descriptor),str(generated/'sensor.proto')],check=True)
        subprocess.run([sys.executable,str(generator),'-D',str(generated),str(descriptor)],check=True)
        header=generated/'sensor.pb.h'
        text=header.read_text(encoding='utf-8').replace('#include <pb.h>','#include "../third_party/nanopb/pb.h"')
        header.write_text(text,encoding='utf-8',newline='\n')
    for name in ('sensor.proto','messages.proto'):
        shutil.copyfile(generated/'sensor.proto',server/name)
    subprocess.run([args.protoc,'-I',str(server),'--python_out='+str(server),str(server/'messages.proto')],check=True)
    print('Generated nanopb and server protocol. Run Validate-Release.ps1 and firmware builds.')


if __name__=='__main__':
    main()
