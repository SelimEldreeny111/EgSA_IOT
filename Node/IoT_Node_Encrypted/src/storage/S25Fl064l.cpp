/** @file S25Fl064l.cpp @brief Explicit 4-byte read/program/erase commands; no chip erase or NV-register writes. */
#include "../config/AppConfig.h"
#if APP_ENABLE_SPI_FLASH
#include "S25Fl064l.h"
#include <Arduino.h>
namespace WiotStorage {
S25Fl064l::S25Fl064l(uint32_t mo,uint32_t mi,uint32_t ck,uint32_t cs,uint32_t hz,uint32_t expected):
    spi_(mo,mi,ck),settings_(hz,MSBFIRST,SPI_MODE0),cs_(cs),expected_(expected) {}
void S25Fl064l::select(){spi_.beginTransaction(settings_);digitalWrite(cs_,LOW);}
void S25Fl064l::release(){digitalWrite(cs_,HIGH);spi_.endTransaction();}
void S25Fl064l::command(uint8_t c){select();spi_.transfer(c);release();}
uint8_t S25Fl064l::status(uint8_t c){select();spi_.transfer(c);const uint8_t r=spi_.transfer(0xFF);release();return r;}
void S25Fl064l::address(uint8_t c,uint32_t a){spi_.transfer(c);for(int i=3;i>=0;--i)spi_.transfer(uint8_t(a>>(8*i)));}
bool S25Fl064l::begin(){
    digitalWrite(cs_,HIGH);pinMode(cs_,OUTPUT);spi_.begin();
    command(0xAB);delayMicroseconds(50);asleep_=false;
    select();spi_.transfer(0x9F);id_=0;for(unsigned i=0;i<3;++i)id_=(id_<<8)|spi_.transfer(0xFF);release();
    available_=id_==expected_;failed_=false;pending_=false;
    return available_ && !(status(0x05)&1U);
}
bool S25Fl064l::wake(){if(!available_||failed_)return false;if(asleep_){command(0xAB);delayMicroseconds(50);asleep_=false;}return true;}
bool S25Fl064l::sleep(){if(!available_||failed_||pending_)return false;if(!asleep_){command(0xB9);asleep_=true;}return true;}
bool S25Fl064l::read(uint32_t a,uint8_t* p,size_t n){
    if(!p||a>8388608U||n>8388608U-a||pending_||!wake())return false;
    select();address(0x13,a);while(n--)*p++=spi_.transfer(0xFF);release();return true;
}
bool S25Fl064l::writeEnabled(){
    if(pending_||!wake()||(status(0x05)&1U))return false;
    command(0x06);return (status(0x05)&2U)!=0;
}
bool S25Fl064l::program(uint32_t a,const uint8_t* p,size_t n){
    if(!p||!n||n>256U-(a&255U)||a>=8388608U||n>8388608U-a||!writeEnabled())return false;
    select();address(0x12,a);while(n--)spi_.transfer(*p++);release();
    pending_=true;started_=millis();timeout_=10;return true;
}
bool S25Fl064l::erase(uint32_t a){
    if((a&4095U)||a>=8388608U||!writeEnabled())return false;
    select();address(0x21,a);release();pending_=true;started_=millis();timeout_=1000;return true;
}
Poll S25Fl064l::poll(){
    if(failed_||!available_)return Poll::Failed;
    if(!pending_)return Poll::Ready;
    const uint8_t sr=status(0x05),err=status(0x07);
    if((err&0x60U)||((sr&1U)&&millis()-started_>=timeout_)){failed_=true;pending_=false;return Poll::Failed;}
    if(sr&1U)return Poll::Busy;
    pending_=false;return Poll::Ready;
}
}
#endif
