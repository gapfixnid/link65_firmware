VIA_ENABLE = yes
DEBOUNCE_TYPE = sym_defer_pk
EEPROM_DRIVER = legacy_stm32_flash
LTO_ENABLE = yes
# Serial LTO avoids native Windows backslash paths in GCC's generated makefile.
LDFLAGS += -flto=1
CONSOLE_ENABLE = no
COMMAND_ENABLE = no
MCU_LDSCRIPT = STM32F103_link65_studio_64k
