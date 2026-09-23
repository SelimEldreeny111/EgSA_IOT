#pragma once

// Copy this file to AppSecrets.hpp and replace every byte with the production
// AES-128 key. AppSecrets.hpp is intentionally ignored by Git.
#define WIOT_AES_KEY_BYTES \
    { \
        0x00, 0x01, 0x02, 0x03, \
        0x04, 0x05, 0x06, 0x07, \
        0x08, 0x09, 0x0A, 0x0B, \
        0x0C, 0x0D, 0x0E, 0x0F \
    }
