""" uf2_info.py 

Display information of the UF2 file.
- display information on the different parts of the UF2file
- display the files in the file container.
"""

import ctypes
import struct
import sys
from pathlib import Path

from uf2conv import (UF2_MAGIC_END, UF2_MAGIC_START0, UF2_MAGIC_START1, is_uf2,
                     load_families)

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
    UF2_EXTENSION_TAGS_PRESENT: "Extension tags present"
}

LITTLEFS_MAGIC = b'\xF0\x0F\xFF\xF7littlefs/\xE0\x00\x10'
LITTLEFS_STR = '\x03\x00\x00\x00\x0flittlefs/\x00\x10'

appstartaddr = 0x2000
familyid = 0x0

#The UF2 file consists of 512 byte blocks, each of which is self-contained and independent of others. 
# Each 512 byte block consists of (see below for details):
#  - magic numbers at the beginning and at the end
#  - address where the data should be flashed
#  - up to 476 bytes of data
# The magic numbers let the microcontroller distinguish an UF2 file block from other data 
class UF2_Block(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ : list[tuple[str, type]] = [
        ("magicStart0", ctypes.c_uint32), # 0
        ("magicStart1", ctypes.c_uint32), # 1
        ("flags", ctypes.c_uint32), # 2 
        ("targetAddr", ctypes.c_uint32), #3 
        ("payloadSize", ctypes.c_uint32),# 4 
        ("blockNo", ctypes.c_uint32),# 5
        ("numBlocks", ctypes.c_uint32),# 6
        ("reserved", ctypes.c_uint32), # 7
        ("data", ctypes.c_uint8 * 476),
        ("magicEnd", ctypes.c_uint32)
    ]

families = load_families()
def print_flags(block: UF2_Block):
    # iterate over the flag descriptions and print the ones that match the flags in this_flag
    for flag_value, flag_description in flag_descriptions.items():
        if flag_value & block.flags:
            if flag_value == UF2_FAMILY_ID_PRESENT:
                print(f"   - {flag_description} : 0x{block.reserved:_X} == {get_family_name(families, block.reserved)}")
            else:
                print(f"   - {flag_description}")


def dump_uf2_file(filename):
    global appstartaddr
    global familyid



    with open(filename, mode='rb') as f:
        buf = f.read()
    if not is_uf2(buf):
        print("Not a UF2 file")
        return None
    print("Info on UF2 file")
    numblocks = len(buf) // UF2_BLOCK_SIZE
    curraddr = 0
    currfamilyid = None
    families_found = {}
    prev_flag = None
    all_flags_same = True

    print ("Number of blocks: ", numblocks)
    for blockno in range(numblocks):
        ptr = blockno * 512
        raw_block = buf[ptr:ptr + 512]
        hd = struct.unpack(b"<IIIIIIII", raw_block[:32])
        block = UF2_Block.from_buffer_copy(raw_block)
        if block.magicStart0 != UF2_MAGIC_START0 or block.magicStart1 != UF2_MAGIC_START1:
            print(f"Skipping block at {ptr}; bad magic")
            continue

        if prev_flag != block.flags:
            print(f"\n{blockno=}")
            # print(f" - {block.magicStart0=}")
            # print(f" - {block.magicStart1=}")
            print(f" - {block.flags=:0b}")
            print_flags(block)
            print(f" - {block.payloadSize=}")
            # print(f" - {block.blockNo=}")
            print(f" - {block.numBlocks=}")
            # print(f" - {block.reserved=}")

        if block.flags & UF2_NOFLASH:
            # NO-flash flag set; skip block
            continue
        if block.payloadSize > 476:
            assert False, f"Invalid UF2 data size at {ptr}"

        newaddr = block.targetAddr

        # The LittleFS marker must be on a 4K boundary
        if block.targetAddr % 4096 == 0:
            
            # check for a littleFS file system in the binary data 
            # do this by matching the magic number for littleFS in the block.data 
            # if found, then print the file system information
            if LITTLEFS_MAGIC in bytes(block.data):
                print(" > Found LittleFS file system header at 0x{:08_X}".format(newaddr))
                # print("  0x{:08_X} : {}".format(newaddr, "littlefs"))

                # // The superblock for littlefs is in both block 0 and 1, but block 0 may be erased
                # // or partially written, so search both blocks 0 and 1 for the littlefs signature.                


        # determine family ID
        if block.flags & UF2_FAMILY_ID_PRESENT and currfamilyid is None:
            currfamilyid = block.reserved
            print( f" - Family ID: 0x{block.reserved:08_X}")
        # determine switch to new family ID
        if curraddr == 0 or (
            (block.flags & UF2_FAMILY_ID_PRESENT)
            and block.reserved != currfamilyid
        ):
            currfamilyid = block.targetAddr
            curraddr = newaddr
            if familyid in [0x0, block.targetAddr]:
                appstartaddr = newaddr
        # check block allignment, order and padding
        padding = newaddr - curraddr
        if padding < 0:
            assert False, f"Block out of order at {ptr}"
        if padding > 10*1024*1024:
            print("ERROR:", f"More than 10M of padding needed at {ptr}")
        if padding % 4 != 0:
            assert False, f"Non-word padding size at {ptr}"

        # no need to output data 
        # if familyid == 0x0 or ((block.flags & UF2_FAMILY_ID_PRESENT ) and familyid == block.reserved):
            # outp.append(block.data[:block.payloadSize])

        curraddr = newaddr + block.payloadSize

        # Keep track of the lowest address value for each family ID found in the UF2 firmware file. 
        # This information is later used to determine the start address of each firmware section 
        # for that family ID.
        if block.flags & UF2_FAMILY_ID_PRESENT:
            if block.reserved in families_found.keys():
                if families_found[block.reserved] > newaddr:
                    families_found[block.reserved] = newaddr
            else:
                families_found[block.reserved] = newaddr

        if prev_flag == None:
            prev_flag = block.flags
        if prev_flag != block.flags:
            all_flags_same = False

        if blockno == (numblocks - 1):
            print("\n --- UF2 File Header Info ---")
            for family_hex in families_found.keys():
                family_short_name = get_family_name(families, family_hex)
                print("Family ID is {:s}, hex value is 0x{:08_X}".format(family_short_name,family_hex))
                print("Target Address is 0x{:08_X}".format(families_found[family_hex]))

            if all_flags_same:
                print("All block flag values consistent, 0x{:04x}".format(hd[2]))
            else:
                print("Flags were not all the same")
            print("----------------------------")
            if len(families_found) > 1 and familyid == 0x0:
                outp = []
                appstartaddr = 0x0 

def get_family_name(families, family_hex):
    family_short_name = ""
    for name, value in families.items():
        if value == family_hex:
            family_short_name = name
    return family_short_name           

def main():
    if len(sys.argv) <= 1 : file_name = "tools\\pico-w.uf2"
    else                  : file_name = sys.argv[1]    
    filename = Path(file_name)
    dump_uf2_file(filename)
 


if __name__ == '__main__':
    main()

