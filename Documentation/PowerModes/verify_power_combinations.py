"""Check all active power-policy combinations against the real AppConfig guards.

Read-only to firmware. Uses existing Arduino preprocessing fakes; does not
compile/link firmware and does not inspect AppSecrets or private AppConfig.cpp.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', default='g++')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    node = root / 'Node' / 'IoT_Node_Encrypted'
    header = node / 'src' / 'config' / 'AppConfig.h'
    fakes = node / 'tests' / 'remote_wake' / 'fakes'
    compiler = shutil.which(args.compiler) or str(Path(args.compiler).resolve())
    env = dict(os.environ)
    env['PATH'] = str(Path(compiler).parent) + os.pathsep + env['PATH']
    rows = []
    for transport, radio_modes in [('SIM', range(2)), ('WIFI', range(2)), ('LORA', range(3))]:
        for controller in range(5):
            for radio in radio_modes:
                expected = ((controller in (0, 2) and radio == 0) or
                            (transport != 'SIM' and controller in (1, 4) and radio == 1) or
                            (transport == 'LORA' and controller == 3 and radio == 2))
                rows.append(dict(role='node', transport=transport, controller=controller,
                                 lora=radio if transport == 'LORA' else 0,
                                 wifi=radio if transport == 'WIFI' else 0,
                                 sim=radio if transport == 'SIM' else 0,
                                 wor_tx=0, expected=expected))
    for transport in ('SIM', 'WIFI'):
        for controller in range(5):
            for lora in range(3):
                for radio in range(2):
                    for wor_tx in range(2):
                        rows.append(dict(role='gateway', transport=transport,
                                         controller=controller, lora=lora,
                                         wifi=radio if transport == 'WIFI' else 0,
                                         sim=radio if transport == 'SIM' else 0,
                                         wor_tx=wor_tx,
                                         expected=controller == 0 and lora == 0 and radio == 0))
    for row in rows:
        defines = dict(APP_ROLE=2 if row['role'] == 'gateway' else 1,
                       APP_UPLINK=2 if row['transport'] == 'LORA' else 1,
                       APP_CONTROLLER_POWER_MODE=row['controller'],
                       APP_LORA_POWER_MODE=row['lora'], APP_WIFI_POWER_MODE=row['wifi'],
                       APP_SIM_POWER_MODE=row['sim'], APP_LORA_GATEWAY_WOR_TX=row['wor_tx'])
        modem = 'USE_ESP8266' if row['transport'] == 'WIFI' else 'USE_SIM800'
        command = [compiler, '-E', '-P', '-x', 'c++', '-I', str(fakes), '-D' + modem]
        command += [f'-D{k}={v}' for k, v in defines.items()]
        command += [str(header), '-o', os.devnull]
        result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=20)
        row['accepted'] = result.returncode == 0
        row['passed'] = row['accepted'] == row['expected']
        if not row['accepted']:
            row['guard_messages'] = [line.strip() for line in result.stderr.splitlines() if 'error:' in line]
            if not row['guard_messages']:
                raise RuntimeError('Compiler failed without expected policy #error: ' + result.stderr)
        if not row['passed']:
            raise AssertionError(json.dumps(row) + '\n' + result.stderr)
    report = dict(firmware_revision='48e5e4b', scope='Actual AppConfig preprocessor guards only',
                  total=len(rows), accepted=sum(r['accepted'] for r in rows),
                  rejected=sum(not r['accepted'] for r in rows), all_passed=True, cases=rows)
    assert (report['total'], report['accepted'], report['rejected']) == (155, 15, 140)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f"PASS: {report['total']} combinations; {report['accepted']} accepted, {report['rejected']} rejected as expected")


if __name__ == '__main__':
    main()
