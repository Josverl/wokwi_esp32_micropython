""" uf2_info.py 

Display information of the UF2 file.
- display information on the different parts of the UF2file
- find little fs file system in the UF2 file
- find the different ranges in the UF2 file
- find the different families in the UF2 file
- find the binary information in the UF2 file ( rp2040 only, using picotool ) 

"""

import ctypes
import re
import struct
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional

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


# The UF2 file consists of 512 byte blocks, each of which is self-contained and independent of others.
# Each 512 byte block consists of (see below for details):
#  - magic numbers at the beginning and at the end
#  - address where the data should be flashed
#  - up to 476 bytes of data
# The magic numbers let the microcontroller distinguish an UF2 file block from other data
# class UF2_Block(ctypes.LittleEndianStructure):
#     _pack_ = 1
#     _fields_: list[tuple[str, type]] = [
#         ("magicStart0", ctypes.c_uint32),  # 0
#         ("magicStart1", ctypes.c_uint32),  # 1
#         ("flags", ctypes.c_uint32),  # 2
#         ("targetAddr", ctypes.c_uint32),  # 3
#         ("payloadSize", ctypes.c_uint32),  # 4
#         ("blockNo", ctypes.c_uint32),  # 5
#         ("numBlocks", ctypes.c_uint32),  # 6
#         ("reserved", ctypes.c_uint32),  # 7
#         ("data", ctypes.c_uint8 * 476),
#         ("magicEnd", ctypes.c_uint32),
#     ]


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

    def __init__(self, data: Optional[bytes] = None):
        super().__init__()
        self.magicStart0 = UF2_MAGIC_START0
        self.magicStart1 = UF2_MAGIC_START1
        self.magicEnd = UF2_MAGIC_END
        if data:
            if len(data) > 476:
                raise ValueError(f"Data too long: {len(data)}")
            # copy the data to the data field, padded with 0x00
            self.data = (ctypes.c_uint8 * 476).from_buffer_copy(data + b"\0" * (478 - len(data)))

    @property
    def is_uf2_block(self):
        return self.magicStart0 == UF2_MAGIC_START0 and self.magicStart1 == UF2_MAGIC_START1 and self.magicEnd == UF2_MAGIC_END


def print_flags(block: UF2_Block):
    print(f" - {block.blockNo=}")
    print(f" - {block.flags=:0b}")
    # iterate over the flag descriptions and print the ones that match the flags in this_flag
    for flag_value, flag_description in flag_descriptions.items():
        if flag_value & block.flags:
            if flag_value == UF2_FAMILY_ID_PRESENT:
                print(f"   - {flag_description} : 0x{block.reserved:_X}")  #  == {get_family_name(families, block.reserved)}"
            else:
                print(f"   - {flag_description}")
    print(f" - {block.payloadSize=}")
    print(f" - {block.numBlocks=}")


def convert_to_uf2(file_content, familyid: int, start_addr: int) -> List[UF2_Block]:
    datapadding = b""
    while len(datapadding) < 512 - 256 - 32 - 4:
        datapadding += b"\x00\x00\x00\x00"
    numblocks: int = (len(file_content) + 255) // 256
    uf2_range: List[UF2_Block] = []
    for blockno in range(numblocks):
        ptr = 256 * blockno
        chunk = file_content[ptr : ptr + 256]
        block = UF2_Block(chunk)
        block.flags = 0x0
        if familyid:
            block.flags |= 0x2000
            block.reserved = familyid
        block.targetAddr = start_addr + ptr
        block.payloadSize = len(chunk)

        # hd = struct.pack(b"<IIIIIIII",
        #     UF2_MAGIC_START0, UF2_MAGIC_START1,
        #     flags, ptr + start_addr, 256, blockno, numblocks, familyid)
        # while len(chunk) < 256:
        #     chunk += b"\x00"
        # block = hd + chunk + datapadding + struct.pack(b"<I", UF2_MAGIC_END)
        # assert len(block) == 512
        uf2_range.append(block)
    # add blockcount to each block
    my_len = len(uf2_range)
    for i, block in enumerate(uf2_range):
        block.numBlocks = my_len
        block.blockNo = i
    return uf2_range


from collections import UserList


class UF2File(UserList):
    """A list-like object that reads UF2 blocks from an underlying file object"""

    def __init__(self, iterable=None):
        if iterable is None:
            iterable = []
        super().__init__(str(item) for item in iterable)
        self.data = []
        self.families: Dict[str, int] = {}
        self.littlefs_superblocks = []
        # list of blocknumbers where the littlefs file system starts
        self.ranges = []
        # list of tuples (start, end) of the different ranges in the file
        self.known_families = load_families()

        self.program_name = ""
        self.binary_start = 0
        self.binary_end = 0
        self.drive_start = 0
        self.drive_end = 0
        self.board = ""
        # appstartaddr = 0x2000

    def __len__(self):
        return len(self.data)

    def __getitem__(self, key):
        return self.data[key]

    def __iter__(self):
        return iter(self.data)

    def __setitem__(self, index, item: UF2_Block):
        self.data[index] = item

    def insert(self, index, item: UF2_Block):
        self.data.insert(index, item)

    def read_uf2(self, filepath: Path):
        self.uf2_file = filepath
        # self._buffer = b''
        # self._pos = 0
        # read UF2 blocks from the file and populate the blocks attribute
        with open(filepath, "rb") as f:
            while True:
                data = f.read(ctypes.sizeof(UF2_Block))
                if not data:
                    break
                block = UF2_Block.from_buffer_copy(data)
                if not block.is_uf2_block:
                    print(f"Skipping block {block.blockNo}; bad magic")
                    continue
                self.data.append(block)
        self.scan()

    def append(self, block: UF2_Block):
        if block.targetAddr < self.data[-1].targetAddr + self.data[-1].payloadSize:
            raise ValueError(f"Block {block.blockNo} at 0x{block.targetAddr:08_X} is before the last block")
        block.blockNo = len(self.data)
        self.data.append(block)

    def extend(self, other: Iterable[UF2_Block]):
        for block in other:
            self.append(block)
        # # todo: update .numblocks in ALL blocks in self.
        # for i, block in enumerate(self.data):
        #     block.numBlocks = len(self.data)
        #     block.blockNo = i

    def __str__(self) -> str:
        result = ""
        # blocks
        result += f"Number of blocks: {len(self)}\n"
        result += f"Program name: {self.program_name}\n"
        result += f"Board: {self.board}\n"
        # familiy
        result += f"Number of families: {len(self.families)}\n"
        for family, addr in self.families.items():
            result += f" - Family {family} at 0x{addr:08_X}\n"
        # ranges
        result += f"Number of ranges: {len(self.ranges)}\n"
        for i, (start, end) in enumerate(self.ranges):
            result += f" - Range {i}: 0x{start:08_X} - 0x{end:08_X}\n"
        # Drives
        # LittleFS
        result += f"LittleFS superblocks: {len(self.littlefs_superblocks)}\n"
        for i, blockno in enumerate(self.littlefs_superblocks):
            result += f" - LittleFS superblock {i}: block {blockno} at 0x{self.data[blockno].targetAddr:08_X}\n"
        result += "Pico drive info\n"
        result += f" - Drive start: 0x{self.drive_start:08_X}\n"
        result += f" - Drive end: 0x{self.drive_end:08_X}\n"
        return result

    def get_family_name(self, family_hex):
        family_short_name = ""
        for name, value in self.known_families.items():
            if value == family_hex:
                family_short_name = name
        return family_short_name

    def scan(self):
        self.scan_family_names()
        self.scan_ranges()
        self.scan_littlefs()

    def scan_ranges(self):
        # scan the blocks for the start of the different ranges
        # a range is a series of blocks withouth padding in between
        self.ranges = []
        last_address = 0
        start_range = 0
        end_range = 0
        # iterate over the blocks and check if the block is a range start or end    # add the start and end addresses of the range to the ranges list
        for block in self.data:
            if start_range == 0:
                start_range = block.targetAddr
                last_address = block.targetAddr + block.payloadSize
            elif last_address != block.targetAddr or block.data[: block.payloadSize] == b"\x00" * block.payloadSize:
                # gap detected, end of range
                # is the block all 0x00?
                # block is all 0x00, end of range
                end_range = last_address
                self.ranges.append((start_range, end_range))
                start_range = block.targetAddr
                end_range = 0
                last_address = block.targetAddr + block.payloadSize
            else:
                # next block in the range leaves no gap
                last_address = block.targetAddr + block.payloadSize

        # add the last range
        end_range = last_address
        self.ranges.append((start_range, end_range))

    def scan_littlefs(self):
        for block in self.data:
            if block.targetAddr % 4096 == 0 and LITTLEFS_MAGIC in bytes(block.data):
                print(f" > Found LittleFS file system header in block {block.blockNo} at 0x{block.targetAddr:08_X}")
                self.littlefs_superblocks.append(block.blockNo)
                # print("  0x{:08_X} : {}".format(newaddr, "littlefs"))
                # // The superblock for littlefs is in both block 0 and 1, but block 0 may be erased
                # // or partially written, so search both blocks 0 and 1 for the littlefs signature.

    def scan_family_names(self):
        for block in self.data:
            if block.flags & UF2_FAMILY_ID_PRESENT:
                fam_id = block.reserved
                fam_name = self.get_family_name(fam_id)
                if fam_name not in self.families.keys():
                    # store address for this family
                    self.families[fam_name] = block.targetAddr
                else:
                    # store lowest address for this family
                    self.families[fam_name] = min(self.families[fam_name], block.targetAddr)

    def parse_output(
        self,
        output,
        qry,
    ) -> str:
        return match[1] if (match := re.search(qry, output)) else "42"

    def add_bin_info(self, uf2_file: Optional[Path] = None):
        # sourcery skip: extract-method
        # read the binary information using picotool and add the information to the class

        # supplied or previously read uf2 file
        uf2_file = uf2_file or self.uf2_file
        if not uf2_file:
            print("No UF2 file loaded")
            return
        if "RP2040" in self.families.keys():
            # use picotool to read the binary information
            # shell=true allows same command for Linux & Windows
            picopath = Path(__file__).parent / "picotool"
            try:
                result = subprocess.run(
                    [picopath, "info", "-a", str(self.uf2_file)],
                    capture_output=True,
                    text=True,
                    shell=True,
                )
            except OSError:
                print("picotool not found")
                return
            if result.returncode == 0:
                self.program_name = self.parse_output(result.stdout, r"\s+name:\s+(\w+)")
                self.board = self.parse_output(result.stdout, r"\s+pico_board:\s+(\w+)")
                # convert from hex_string to int
                self.binary_start = int(self.parse_output(result.stdout, r"binary start:\s+(0[xX][0-9a-fA-F]+)"), 16)
                self.binary_end = int(self.parse_output(result.stdout, r"binary end:\s+(0[xX][0-9a-fA-F]+)"), 16)
                self.drive_start = int(self.parse_output(result.stdout, r"embedded drive:\s+(0[xX][0-9a-fA-F]+)"), 16)
                self.drive_end = int(
                    self.parse_output(
                        result.stdout,
                        r"embedded drive:\s+0[xX][0-9a-fA-F]+-(0[xX][0-9a-fA-F]+)",
                    ),
                    16,
                )


def main(
    file_name="firmware\\rp2-pico-20230426-v1.20.0.uf2",
    littlefs_img=Path("build\\littlefs.img"),
    out_path=Path("build\\pico_src.uf2"),
):
    # file_name = "firmware\\rp2-pico-w-20230426-v1.20.0.uf2" if len(sys.argv) <= 1 else sys.argv[1]
    # file_name = "firmware\\SEEED_WIO_TERMINAL-20230426-v1.20.0.uf2"
    file_path = Path(file_name)

    # dump_uf2_file(filename)

    # out_path = None

    firmware_uf2 = UF2File()
    firmware_uf2.read_uf2(file_path)
    firmware_uf2.add_bin_info()
    print(firmware_uf2)

    littelfs_uf2 = None
    # read the littlefs image from build folder
    if littlefs_img and littlefs_img.exists():
        littelfs_uf2 = read_image(littlefs_img, firmware_uf2)
    if littelfs_uf2:
        # write to file
        with open("build\\littlefs.uf2", "wb") as f:
            for block in littelfs_uf2:
                f.write(block)

        # add the littlefs image to the uf2 file
        firmware_uf2.extend(littelfs_uf2)

    foo = UF2_Block("foo".encode())
    foo.targetAddr = 0x1020_0000
    foo.payloadSize = 256

    firmware_uf2.append(foo)

    if out_path:
        # write the new uf2 file

        firmware_uf2.scan()
        print(f"Writing {len(firmware_uf2)} blocks to {out_path}")
        print(firmware_uf2)  # print the new uf2 file

        with open(out_path, "wb") as f:
            for block in firmware_uf2:
                f.write(block)


def read_image(littlefs_img, firmware_uf2, trunkate=False):
    print(f"Reading littlefs image from {littlefs_img}")

    with open(littlefs_img, "rb") as f:
        littlefs_img = f.read()
    print(">--------------------------------<")
    print(f"LittleFS image size: {len(littlefs_img)} bytes = {len(littlefs_img)//1024}Kb")

    if trunkate:
        # trunkate the littlefs image to remove b`\xff` * 255 at the end of the buffer
        while littlefs_img[-255:] == b"\xff" * 255:
            littlefs_img = littlefs_img[:-255]
        print(f"TRUNKATED size : {len(littlefs_img)} bytes = {len(littlefs_img)//1024}Kb")

    fam_str = list(firmware_uf2.families.keys())[0]
    # convert the littlefs image to uf2 blocks
    result = convert_to_uf2(
        littlefs_img,
        firmware_uf2.known_families[fam_str],
        firmware_uf2.drive_start,
    )
    print(f"LittleFS image size: {len(result)} blocks")

    return result


if __name__ == "__main__":
    main()
