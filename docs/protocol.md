# Link65 Studio protocol

USB VID/PID `4F53:4C49`, Raw HID usage page/usage `FF60:61`.
Reports contain 32 payload bytes and use report ID 0 (unnumbered).
VIA protocol 13, negotiated QMK keycode version `0.0.9`.
Four layers, 5 x 15 matrix cells, 67 physical keys, 16 macros, 1407 macro bytes.

VIA `02 7E` returns `L65S`, capability schema 1, flags 1: matrix reads.
VIA `02 03 <row offset>` returns debounced matrix rows as big-endian uint16.
VIA `0B` is rejected with `FF`; software DFU entry is not supported.
Physical entry: disconnect USB, hold B, reconnect USB, release B.

The setting project consumes this protocol through WebHID; firmware builds do
not import setting-project files. See https://github.com/gapfixnid/link65_setting.
