
from dataclasses import dataclass
from typing import List

VFS_LFS1 = 0x0001_0000
VFS_LFS2 = 0x0002_0000

VFLASH_BLOCK_SIZE = 4096

@dataclass
class PortDiskInfo:
    name: str
    page_size: int
    block_size: int
    block_count: int
    image_size: int = -1
    vfstype: int = VFS_LFS2

    def __post_init__(self):
        # CALC image size
        if self.image_size == -1:
            self.image_size = self.block_size * self.block_count

# rp2_common
FLASH_PAGE_SIZE = 256
FLASH_SECTOR_SIZE = 4096  # :=> LittleFS Block
# FLASH_BLOCK_SIZE = 65536


port_info_list: List[PortDiskInfo] = [
    PortDiskInfo("esp32-generic", 256, VFLASH_BLOCK_SIZE, 512),
    PortDiskInfo("esp8266-generic", 256, VFLASH_BLOCK_SIZE, 512),
    PortDiskInfo("rp2-pico", 256, VFLASH_BLOCK_SIZE, 352),  # pico  = 0x100a0000-0x10200000 (1408K):
    PortDiskInfo("rp2-pico-w", 256, VFLASH_BLOCK_SIZE, 208),
    # PortDiskInfo("pimoroni_picolipo_16mb", 256, VFLASH_BLOCK_SIZE, 3840), # 0x10100000-0x11000000 (15360K)
    # PortDiskInfo("SAMD", 1536, VFLASH_BLOCK_SIZE, 512),
]


# define BLOCK_SIZE_BYTES (FLASH_SECTOR_SIZE) # rp2
# Port/board,               PageSize,   Block Size, Block_count, Image Size
# esp32,                    256,        4096,       512           2_097_152 (0X200_000)
# esp8266,                  256,        8192?4096,  512           1_024_000 (0xFA_000)?


# pico  = 0x100a0000-0x10200000 (1408K):
# pico,                     256,        4096,       352           1_443_328 (0x160_000)


# pico_w = 0x1012c000-0x10200000 (848K)
# pico_w,                   256,        4096,       208           852_992 (0xD0_000)

# pimoroni_picolipo_16mb = 0x10100000-0x11000000 (15360K)
# pimoroni_picolipo_16mb,   256,        4096?,      3840,           1_572_864 (0x180_000)

# SAMD
# define VFS_BLOCK_SIZE_BYTES            (1536) // SAMD51

# PICO_LIPO_16
# ports\rp2\boards\PIMORONI_PICOLIPO_16MB\mpconfigboard.h
# define MICROPY_HW_FLASH_STORAGE_BYTES (15 * 1024 * 1024) 0x00F0_0000
