#!/usr/bin/env python3
"""
NyxWin Mach-O Binary Rewriter (Patch #31 Engine)
Universal iOS 14.0–17.9 compatibility patcher for SwiftUICore.framework.
Converts LC_LOAD_DYLIB to LC_LOAD_WEAK_DYLIB and remaps chained fixups.
"""

import sys
import struct
import os

MH_MAGIC_64 = 0xFEEDFACF
MH_CIGAM_64 = 0xCFFAEDFE

LC_LOAD_DYLIB = 0x0C
LC_LOAD_WEAK_DYLIB = 0x80000018
LC_DYLD_CHAINED_FIXUPS = 0x80000034

DYLD_CHAINED_IMPORT = 1
DYLD_CHAINED_IMPORT_ADDEND = 2
DYLD_CHAINED_IMPORT_ADDEND64 = 3

def patch_macho_binary(file_path: str, verbose: bool = True) -> bool:
    if not os.path.isfile(file_path):
        if verbose:
            print(f"[ERROR] Mach-O file not found: {file_path}")
        return False

    with open(file_path, "r+b") as f:
        data = bytearray(f.read())
        if len(data) < 32:
            if verbose:
                print("[ERROR] Binary too small to be a 64-bit Mach-O.")
            return False

        magic = struct.unpack_from("<I", data, 0)[0]
        if magic != MH_MAGIC_64:
            if verbose:
                print(f"[SKIP] Not a 64-bit Mach-O binary (magic: {hex(magic)}).")
            return True

        ncmds, sizeofcmds = struct.unpack_from("<II", data, 16)
        offset = 32  # sizeof(mach_header_64)

        swiftui_core_ordinal = -1
        swiftui_ordinal = -1
        dylib_index = 0

        chained_fixups_cmd_offset = 0
        chained_fixups_data_offset = 0
        chained_fixups_data_size = 0

        # Pass 1: Scan load commands
        cmd_offset = offset
        for _ in range(ncmds):
            if cmd_offset + 8 > len(data):
                break
            cmd, cmdsize = struct.unpack_from("<II", data, cmd_offset)

            if cmd in (LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB):
                dylib_index += 1
                name_offset = struct.unpack_from("<I", data, cmd_offset + 8)[0]
                str_start = cmd_offset + name_offset
                str_end = data.find(b"\x00", str_start)
                if str_end != -1:
                    dylib_name = data[str_start:str_end].decode("utf-8", errors="ignore")
                    if "SwiftUICore.framework/SwiftUICore" in dylib_name:
                        swiftui_core_ordinal = dylib_index
                        if cmd == LC_LOAD_DYLIB:
                            # Convert to LC_LOAD_WEAK_DYLIB
                            struct.pack_into("<I", data, cmd_offset, LC_LOAD_WEAK_DYLIB)
                            if verbose:
                                print(f"[+] Converted SwiftUICore (ordinal {dylib_index}) to LC_LOAD_WEAK_DYLIB")
                    elif "SwiftUI.framework/SwiftUI" in dylib_name:
                        swiftui_ordinal = dylib_index

            elif cmd == LC_DYLD_CHAINED_FIXUPS:
                chained_fixups_cmd_offset = cmd_offset
                chained_fixups_data_offset, chained_fixups_data_size = struct.unpack_from("<II", data, cmd_offset + 8)

            cmd_offset += cmdsize

        # Pass 2: Remap chained fixups if SwiftUICore was found
        if swiftui_core_ordinal > 0 and swiftui_ordinal > 0 and chained_fixups_data_offset > 0:
            header_offset = chained_fixups_data_offset
            if header_offset + 28 <= len(data):
                (fixups_version, starts_offset, imports_offset, symbols_offset,
                 imports_count, imports_format, symbols_format) = struct.unpack_from("<IIIIIII", data, header_offset)

                real_imports_offset = header_offset + imports_offset

                if imports_format == DYLD_CHAINED_IMPORT:
                    # 4 bytes per entry: lib_ordinal (8), weak_import (1), name_offset (23)
                    entry_size = 4
                    for i in range(imports_count):
                        entry_pos = real_imports_offset + (i * entry_size)
                        if entry_pos + 4 > len(data):
                            break
                        raw_val = struct.unpack_from("<I", data, entry_pos)[0]
                        lib_ord = raw_val & 0xFF
                        if lib_ord == swiftui_core_ordinal:
                            # Rewrite lib_ordinal to swiftui_ordinal
                            new_val = (raw_val & ~0xFF) | (swiftui_ordinal & 0xFF)
                            struct.pack_into("<I", data, entry_pos, new_val)

                elif imports_format in (DYLD_CHAINED_IMPORT_ADDEND, DYLD_CHAINED_IMPORT_ADDEND64):
                    # 8 bytes per entry: lib_ordinal (16), weak_import (1), name_offset (32), addend (15)
                    entry_size = 8
                    for i in range(imports_count):
                        entry_pos = real_imports_offset + (i * entry_size)
                        if entry_pos + 8 > len(data):
                            break
                        raw_val = struct.unpack_from("<Q", data, entry_pos)[0]
                        lib_ord = raw_val & 0xFFFF
                        if lib_ord == swiftui_core_ordinal:
                            new_val = (raw_val & ~0xFFFF) | (swiftui_ordinal & 0xFFFF)
                            struct.pack_into("<Q", data, entry_pos, new_val)

                if verbose:
                    print(f"[+] Remapped chained fixups imports: {swiftui_core_ordinal} -> {swiftui_ordinal}")

        # Write patched data back
        f.seek(0)
        f.write(data)
        f.truncate()

    if verbose:
        print(f"[+] Mach-O binary patched successfully: {file_path}")
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python patch_macho.py <path_to_macho_executable>")
        sys.exit(1)
    success = patch_macho_binary(sys.argv[1])
    sys.exit(0 if success else 1)
