"""Compile production gateway parser without hardware and test regional routing."""
from pathlib import Path
import subprocess
import tempfile
import unittest

NODE=Path(__file__).resolve().parents[2]/'Node/IoT_Node_Encrypted'

class GatewayRegionTests(unittest.TestCase):
    def test_production_command_parser(self):
        source=r'''
        #include "MqttTopicRouting.h"
        #include <cassert>
        int main() {
            uint16_t node=999; bool broadcast=true;
            const char* prefix="wiot/Company_1/Region_1";
            assert(MqttTopicRouting::parseCommand("wiot/Company_1/Region_1/3/cmd",prefix,node,broadcast));
            assert(node==3 && !broadcast);
            assert(MqttTopicRouting::parseCommand("wiot/Company_1/Region_1/broadcast",prefix,node,broadcast));
            assert(node==0 && broadcast);
            const char* rejected[]={"wiot/Company_1/Region_2/3/cmd","wiot/Company_2/Region_1/3/cmd",
                "wiot/Company_1/Region_1x/3/cmd","wiot/Company_1/Region_1/03/cmd",
                "wiot/Company_1/Region_1/0/cmd","wiot/Company_1/Region_1/65536/cmd",
                "wiot/Company_1/Region_1/3/CMD","wiot/Company_1/Region_1/3/cmd/extra",
                "wiot/Company_1/Region_1/broadcast/cmd","wiot/Company_1/Region_1/+/cmd",
                "wiot/Company_1/Region_1","wiot/Company_1",""};
            for(auto topic:rejected) assert(!MqttTopicRouting::parseCommand(topic,prefix,node,broadcast));
        }'''
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'gateway.cpp';exe=Path(directory)/'gateway.exe'
            path.write_text(source,encoding='utf-8')
            subprocess.run(['g++','-std=c++14','-Wall','-Wextra','-Werror','-I',str(NODE/'src/comm'),
                            str(path),'-o',str(exe)],check=True,capture_output=True)
            subprocess.run([str(exe)],check=True)
