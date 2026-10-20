// Link65 Studio firmware, GPL-3.0-or-later.
#pragma once
#define DEBOUNCE 5
#define USB_POLLING_INTERVAL_MS 1
#define DYNAMIC_KEYMAP_LAYER_COUNT 4
#define DYNAMIC_KEYMAP_MACRO_COUNT 16
#define VIA_FIRMWARE_VERSION 0x00010002
// Keep all firmware and persistent storage within the first 64 KiB.
#define FEE_MCU_FLASH_SIZE 64
#define FEE_PAGE_SIZE 0x400
#define FEE_PAGE_COUNT 4
#define FEE_DENSITY_BYTES 2048
#define FEE_PAGE_BASE_ADDRESS 0x0800F000
