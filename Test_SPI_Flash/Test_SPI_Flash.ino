/**
 * @file Test_SPI_Flash.ino
 * @brief Standalone STM32F401 / S25FL064L SPI wiring and memory bench test.
 * Debug: PA2 TX / PA3 RX, 115200 baud. SPI1: PA4 CS, PA5 SCK,
 * PA6 MISO, PA7 MOSI. No production application libraries are required.
 */
#include <Arduino.h>
#include <SPI.h>

// Leave false for read-only testing. true allows 't' to ERASE the last 4 KB.
// That sector is ALSO used by the production logger; it is NOT reserved.
#ifndef TEST_ALLOW_ERASE
#define TEST_ALLOW_ERASE false
#endif
constexpr uint32_t SPI_CLOCK_HZ = 1000000UL; // Start at 1 MHz; production uses 4 MHz.
constexpr uint32_t EXPECTED_ID = 0x016017UL; // S25FL064L: 01 60 17, 8 MiB.
constexpr uint32_t FLASH_BYTES = 8UL * 1024UL * 1024UL;
constexpr uint32_t SECTOR_BYTES = 4096UL;
constexpr uint32_t TEST_ADDRESS = 0x007FF000UL; // Final 4 KB sector.
static_assert(TEST_ADDRESS % SECTOR_BYTES == 0, "Test sector must be aligned");
static_assert(TEST_ADDRESS <= FLASH_BYTES - SECTOR_BYTES, "Test sector outside flash");

HardwareSerial Debug(PA3, PA2); // Constructor: RX, TX.
SPIClass FlashSPI(PA7, PA6, PA5); // Constructor: MOSI, MISO, SCK.
SPISettings FlashSettings(SPI_CLOCK_HZ, MSBFIRST, SPI_MODE0);

void printHex(uint32_t value, uint8_t digits) {
  const char hex[] = "0123456789ABCDEF";
  for (int shift = (digits - 1) * 4; shift >= 0; shift -= 4)
    Debug.print(hex[(value >> shift) & 0x0F]);
}

void selectFlash() {
  FlashSPI.beginTransaction(FlashSettings);
  digitalWrite(PA4, LOW);
}

void releaseFlash() {
  digitalWrite(PA4, HIGH);
  FlashSPI.endTransaction();
}

void command(uint8_t opcode) {
  selectFlash();
  FlashSPI.transfer(opcode);
  releaseFlash();
}

uint8_t status(uint8_t opcode) {
  selectFlash();
  FlashSPI.transfer(opcode);
  const uint8_t value = FlashSPI.transfer(0xFF);
  releaseFlash();
  return value;
}

uint32_t readId() {
  selectFlash();
  FlashSPI.transfer(0x9F);
  uint32_t id = 0;
  for (uint8_t i = 0; i < 3; ++i) id = (id << 8) | FlashSPI.transfer(0xFF);
  releaseFlash();
  return id;
}

// Explicit four-byte opcodes match the production SPI flash driver.
void sendAddress(uint8_t opcode, uint32_t address) {
  FlashSPI.transfer(opcode);
  for (int shift = 24; shift >= 0; shift -= 8)
    FlashSPI.transfer(uint8_t(address >> shift));
}

void readBytes(uint32_t address, uint8_t *data, size_t count) {
  selectFlash();
  sendAddress(0x13, address);
  while (count--) *data++ = FlashSPI.transfer(0xFF);
  releaseFlash();
}

bool ready(uint32_t timeoutMs) {
  const uint32_t started = millis();
  do {
    const uint8_t sr1 = status(0x05), sr2 = status(0x07);
    if (sr2 & 0x60) {
      Debug.print(F("FAIL: flash program/erase error; SR2=0x"));
      printHex(sr2, 2);
      Debug.println();
      return false;
    }
    if (!(sr1 & 0x01)) return true;
    delay(1);
  } while (uint32_t(millis() - started) < timeoutMs);
  Debug.println(F("FAIL: flash busy timeout."));
  return false;
}

bool writeEnable() {
  if (!ready(2000)) return false;
  command(0x06);
  if (status(0x05) & 0x02) return true;
  Debug.println(F("FAIL: write-enable latch did not set."));
  return false;
}

bool probe() {
  const uint32_t id = readId();
  Debug.print(F("JEDEC ID: "));
  printHex(id, 6);
  Debug.print(F("  expected: 016017\r\nSR1=0x"));
  printHex(status(0x05), 2);
  Debug.print(F("  SR2=0x"));
  printHex(status(0x07), 2);
  Debug.println();
  if (id != EXPECTED_ID) {
    Debug.println(F("FAIL: unexpected ID. Check power, GND, CS and SPI wiring. Writes refused."));
    return false;
  }
  if (!ready(2000)) return false;
  Debug.println(F("PASS: expected flash responds. Capacity: 8388608 bytes (8 MiB)."));
  return true;
}

void dump(uint32_t address) {
  uint8_t bytes[32];
  readBytes(address, bytes, sizeof(bytes));
  for (uint8_t i = 0; i < sizeof(bytes); ++i) {
    if (i % 16 == 0) { printHex(address + i, 8); Debug.print(F(": ")); }
    printHex(bytes[i], 2);
    Debug.print(' ');
    if (i % 16 == 15) Debug.println();
  }
}

bool mismatch(uint32_t address, uint8_t expected, uint8_t actual) {
  Debug.print(F("FAIL at 0x")); printHex(address, 8);
  Debug.print(F(": expected ")); printHex(expected, 2);
  Debug.print(F(", read ")); printHex(actual, 2);
  Debug.println();
  return false;
}

bool memoryTest() {
  if (!TEST_ALLOW_ERASE) {
    Debug.println(F("Read-only mode: 't' refused. Set TEST_ALLOW_ERASE true only for a disposable log."));
    return false;
  }
  if (!probe() || !writeEnable()) return false;
  Debug.println(F("ERASING 0x007FF000..0x007FFFFF. Existing telemetry there will be lost."));
  selectFlash();
  sendAddress(0x21, TEST_ADDRESS);
  releaseFlash();
  if (!ready(2000)) return false;

  uint8_t bytes[32];
  for (uint32_t offset = 0; offset < SECTOR_BYTES; offset += sizeof(bytes)) {
    readBytes(TEST_ADDRESS + offset, bytes, sizeof(bytes));
    for (uint8_t i = 0; i < sizeof(bytes); ++i)
      if (bytes[i] != 0xFF) return mismatch(TEST_ADDRESS + offset + i, 0xFF, bytes[i]);
  }
  Debug.println(F("PASS: all 4096 erased bytes read FF."));
  if (!writeEnable()) return false;
  selectFlash();
  sendAddress(0x12, TEST_ADDRESS);
  for (uint16_t i = 0; i < 256; ++i) FlashSPI.transfer(uint8_t(i ^ 0xA5));
  releaseFlash();
  if (!ready(100)) return false;
  for (uint16_t offset = 0; offset < 256; offset += sizeof(bytes)) {
    readBytes(TEST_ADDRESS + offset, bytes, sizeof(bytes));
    for (uint8_t i = 0; i < sizeof(bytes); ++i) {
      const uint8_t expected = uint8_t((offset + i) ^ 0xA5);
      if (bytes[i] != expected) return mismatch(TEST_ADDRESS + offset + i, expected, bytes[i]);
    }
  }
  command(0x04); // Write disable; leave the pattern available for a reset/read check.
  Debug.println(F("PASS: erase + 256-byte program + exact read-back verified."));
  dump(TEST_ADDRESS);
  return true;
}

void setup() {
  digitalWrite(PA4, HIGH);
  pinMode(PA4, OUTPUT);
  FlashSPI.begin();
  Debug.begin(115200);
  delay(500);
  command(0xAB); // Release deep power-down; no register/protection changes.
  delay(1);
  Debug.println(F("\r\n=== WIOT STM32 SPI FLASH BENCH TEST ==="));
  Debug.println(F("SPI: CS=PA4 SCK=PA5 MISO=PA6 MOSI=PA7; Mode 0"));
  Debug.print(F("SPI clock (Hz): ")); Debug.println(SPI_CLOCK_HZ);
  Debug.print(F("Destructive test enabled: "));
  Debug.println(TEST_ALLOW_ERASE ? F("YES") : F("NO (read-only)"));
  if (probe()) { dump(0); dump(TEST_ADDRESS); }
  Debug.println(F("Commands: r = probe; d = dump; t = optional erase/program/verify."));
}

void loop() {
  if (!Debug.available()) return;
  switch (Debug.read()) {
    case 'r': case 'R': probe(); break;
    case 'd': case 'D': if (probe()) { dump(0); dump(TEST_ADDRESS); } break;
    case 't': case 'T': memoryTest(); break;
    default: break; // Ignore terminal line endings.
  }
}
