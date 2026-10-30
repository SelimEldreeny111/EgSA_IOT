#pragma once
#include "Arduino.h"
#include <vector>
struct SPISettings { SPISettings(uint32_t,int,int){} };
namespace FlashModel {
extern std::vector<uint8_t> memory,transaction;
extern uint32_t address,id,now;
extern unsigned busy;
extern bool enabled,asleep,writeProtect;
void start(); void end(); uint8_t transfer(uint8_t);
}
class SPIClass {
public:
 SPIClass(uint32_t,uint32_t,uint32_t){}
 void begin(){}
 void beginTransaction(const SPISettings&){FlashModel::start();}
 void endTransaction(){FlashModel::end();}
 uint8_t transfer(uint8_t b){return FlashModel::transfer(b);}
};
