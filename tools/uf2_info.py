""" uf2_info.py 

Display information of the UF2 file.
- display information on the different parts of the UF2file
- display the files in the file container.
"""

import ctypes
import io
import struct
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from uf2conv import UF2_MAGIC_START0  # is_uf2,
from uf2conv import UF2_MAGIC_END, UF2_MAGIC_START1, load_families

UF2_NOFLASH = 0x00000001
# If set, the block is "comment" and should not be flashed to the device
UF2_FILE_CONTAINER = 0x00001000
UF2_FAMILY_ID_PRESENT = 0x00002000
# when set, the fileSize/familyID holds a value identifying the board family (usually corresponds to an MCU)
# The current master list of family IDs is maintained in a JSON file.
UF2_MD5_PRESENT = 0x00004000
# when set, the md5 hash of the file is present in the file container
UF2_EXTENSION_TAGS_PRESENT = 0x00008000
# when set, the file container contains tags

UF2_BLOCK_SIZE = 512

flag_descriptions = {
    UF2_NOFLASH: "Do not flash to device",
    UF2_FILE_CONTAINER: "File container",
    UF2_FAMILY_ID_PRESENT: "Family ID present",
    UF2_MD5_PRESENT: "MD5 hash present",
    UF2_EXTENSION_TAGS_PRESENT: "Extension tags present",
}

LITTLEFS_MAGIC = b"\xF0\x0F\xFF\xF7littlefs/\xE0\x00\x10"
LITTLEFS_STR = "\x03\x00\x00\x00\x0flittlefs/\x00\x10"

appstartaddr = 0x2000
familyid = 0x0


# The UF2 file consists of 512 byte blocks, each of which is self-contained and independent of others.
# Each 512 byte block consists of (see below for details):
#  - magic numbers at the beginning and at the end
#  - address where the data should be flashed
#  - up to 476 bytes of data
# The magic numbers let the microcontroller distinguish an UF2 file block from other data
class UF2_Block(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_: list[tuple[str, type]] = [
        ("magicStart0", ctypes.c_uint32),  # 0
        ("magicStart1", ctypes.c_uint32),  # 1
        ("flags", ctypes.c_uint32),  # 2
        ("targetAddr", ctypes.c_uint32),  # 3
        ("payloadSize", ctypes.c_uint32),  # 4
        ("blockNo", ctypes.c_uint32),  # 5
        ("numBlocks", ctypes.c_uint32),  # 6
        ("reserved", ctypes.c_uint32),  # 7
        ("data", ctypes.c_uint8 * 476),
        ("magicEnd", ctypes.c_uint32),
    ]


class UF2Block(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_: list[tuple[str, type]] = [
        ("magicStart0", ctypes.c_uint32),  # 0
        ("magicStart1", ctypes.c_uint32),  # 1
        ("flags", ctypes.c_uint32),  # 2
        ("targetAddr", ctypes.c_uint32),  # 3
        ("payloadSize", ctypes.c_uint32),  # 4
        ("blockNo", ctypes.c_uint32),  # 5
        ("numBlocks", ctypes.c_uint32),  # 6
        ("reserved", ctypes.c_uint32),  # 7
        ("data", ctypes.c_uint8 * 476),
        ("magicEnd", ctypes.c_uint32),
    ]

    @property
    def is_uf2_block(self):
        return (
            self.magicStart0 == UF2_MAGIC_START0
            and self.magicStart1 == UF2_MAGIC_START1
            and self.magicEnd == UF2_MAGIC_END
        )


def print_flags(block: UF2_Block):
    print(f" - {block.blockNo=}")
    print(f" - {block.flags=:0b}")
    # iterate over the flag descriptions and print the ones that match the flags in this_flag
    for flag_value, flag_description in flag_descriptions.items():
        if flag_value & block.flags:
            if flag_value == UF2_FAMILY_ID_PRESENT:
                print(
                    f"   - {flag_description} : 0x{block.reserved:_X}"  #  == {get_family_name(families, block.reserved)}"
                )
            else:
                print(f"   - {flag_description}")
    print(f" - {block.payloadSize=}")
    print(f" - {block.numBlocks=}")


class UF2File:
    """A file-like object that reads UF2 blocks from an underlying file object"""

    def __init__(self):
        self.blocks: list[UF2Block] = []
        self.families: Dict[str, int] = {}
        self.littlefs_superblocks = []
        # list of blocknumbers where the littlefs file system starts
        self.ranges = []
        # list of tuples (start, end) of the different ranges in the file
        self.known_families = load_families()

    def get_family_name(self, family_hex):
        family_short_name = ""
        for name, value in self.known_families.items():
            if value == family_hex:
                family_short_name = name
        return family_short_name

    def read_uf2(self, file):
        # self._file = file
        # self._buffer = b''
        # self._pos = 0
        # read UF2 blocks from the file and populate the blocks attribute
        with open(file, "rb") as f:
            while True:
                data = f.read(ctypes.sizeof(UF2Block))
                if not data:
                    break
                block = UF2Block.from_buffer_copy(data)
                if not block.is_uf2_block:
                    print(f"Skipping block {block.blockNo}; bad magic")
                    continue
                self.blocks.append(block)
        self.scan()

    def scan(self):
        self.scan_family_names()
        self.scan_ranges()
        self.scan_littlefs()

    def __len__(self):
        return len(self.blocks)

    def __getitem__(self, key):
        return self.blocks[key]

    def __iter__(self):
        return iter(self.blocks)

    def scan_ranges(self):
        # scan the blocks for the start of the different ranges
        # a range is a series of blocks withouth padding in between
        last_address = 0
        start_range = 0
        end_range = 0
        # iterate over the blocks and check if the block is a range start or end
        # add the start and end addresses of the range to the ranges list
        # use an iterator to iterate over the blocks
        for i, block in enumerate(self.blocks):
            if start_range == 0:
                start_range = block.targetAddr
                last_address = block.targetAddr + block.payloadSize
            else:
                if (
                    last_address != block.targetAddr
                    or block.data[: block.payloadSize] == b"\x00" * block.payloadSize
                ):
                    # gap detected, end of range
                    # is the block all 0x00?
                    # block is all 0x00, end of range
                    end_range = last_address
                    self.ranges.append((start_range, end_range))
                    start_range = block.targetAddr
                    end_range = 0
                else:
                    # next block in the range leaves no gap
                    last_address = block.targetAddr + block.payloadSize

        # add the last range
        end_range = last_address
        self.ranges.append((start_range, end_range))

    def scan_littlefs(self):
        for block in self.blocks:
            if block.targetAddr % 4096 == 0 and LITTLEFS_MAGIC in bytes(block.data):
                print(
                    f" > Found LittleFS file system header in block {block.blockNo} at 0x{block.targetAddr:08_X}"
                )
                self.littlefs_superblocks.append(block.blockNo)
                # print("  0x{:08_X} : {}".format(newaddr, "littlefs"))
                # // The superblock for littlefs is in both block 0 and 1, but block 0 may be erased
                # // or partially written, so search both blocks 0 and 1 for the littlefs signature.

    def scan_family_names(self):
        for block in self.blocks:
            if block.flags & UF2_FAMILY_ID_PRESENT:
                fam_id = block.reserved
                fam_name = self.get_family_name(fam_id)
                if fam_name not in self.families.keys():
                    # store address for this family
                    self.families[fam_name] = block.targetAddr
                else:
                    # store lowest address for this family
                    self.families[fam_name] = min(
                        self.families[fam_name], block.targetAddr
                    )


#             if all_flags_same:
#                 print("All block flag values consistent, 0x{:04x}".format(hd[2]))
#             else:
#                 print("Flags were not all the same")
#             print("----------------------------")
#             if len(families_found) > 1 and familyid == 0x0:
#                 outp = []
#                 appstartaddr = 0x0


def main():
    file_name = "tools\\pico-w.uf2" if len(sys.argv) <= 1 else sys.argv[1]
    # file_name = "firmware\\rp2-pico-20230426-v1.20.0.uf2"
    filename = Path(file_name)
    # dump_uf2_file(filename)

    uff = UF2File()
    uff.read_uf2(filename)

    for i, family in enumerate(uff.families):
        print(f" - Family {i}: {family}")
    print(f"Number of blocks: {len(uff)}")
    print(f"Number of ranges: {len(uff.ranges)}")
    for i, (start, end) in enumerate(uff.ranges):
        print(f" - Range {i}: 0x{start:08_X} - 0x{end:08_X}")
    print(f"Number of LittleFS superblocks: {len(uff.littlefs_superblocks)}")
    for i, blockno in enumerate(uff.littlefs_superblocks):
        print(
            f" - LittleFS superblock {i}: block {blockno} at 0x{uff.blocks[blockno].targetAddr:08_X}"
        )
    print(f"Number of families: {len(uff.families)}")
    for family, addr in uff.families.items():
        print(f" - Family {family} at 0x{addr:08_X}")


# ports\rp2\rp2_flash.c
# define MICROPY_HW_FLASH_STORAGE_BASE (PICO_FLASH_SIZE_BYTES - MICROPY_HW_FLASH_STORAGE_BYTES)
# ports/rp2/msc_disk.c
# define FLASH_BASE_ADDR     (PICO_FLASH_SIZE_BYTES - MICROPY_HW_FLASH_STORAGE_BYTES)

# PICO
# ports/rp2/boards/pico/mpconfigboard.h
# define MICROPY_HW_FLASH_STORAGE_BYTES          (1408 * 1024)   0x0016_0000
# PICO-W
# ports/rp2/boards/pico-w/mpconfigboard.h
# define MICROPY_HW_FLASH_STORAGE_BYTES          (848 * 1024)   0x000D_0000


# PICO_LIPO_16
# ports\rp2\boards\PIMORONI_PICOLIPO_16MB\mpconfigboard.h
# define MICROPY_HW_FLASH_STORAGE_BYTES (15 * 1024 * 1024) 0x00F0_0000


if __name__ == "__main__":
    main()
