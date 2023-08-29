import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

from littlefs import LittleFS

VFS_LFS1 = 0x0001_0000
VFS_LFS2 = 0x0002_0000


VFLASH_BLOCK_SIZE = 4096


def folder_to_lfs(
    source: str,
    block_size,
    block_count,
    prog_size=256,
    disk_version: int = VFS_LFS2,
    target: str = "build/littlefs.img",
):
    """
    Create Little FS image with the contents of the folder.

    Parameters:
    - folder: source folder to wrap
    - image: destination image file
    - disk_version: LittleFS File System Version 0x0002_0000 needed by micropython builds @v1.20.0
    """
    print(f"Create new filesystem with: {block_count} blocks of {block_size} bytes = {int(block_count*block_size/1024)}Kb")
    fs = LittleFS(
        block_size=block_size,
        block_count=block_count,
        prog_size=prog_size,
        disk_version=disk_version,
    )
    source_path = Path(source)
    print(f"Add files from {source_path}")
    for filename in source_path.rglob("*"):
        lfs_fname = f"/{filename.relative_to(source_path).as_posix()}"
        if filename.is_file():
            with open(filename, "rb") as src_file:
                # use the relative path to source as the littlefs filename
                print(f"Adding {lfs_fname}")
                with fs.open(lfs_fname, "wb") as lfs_file:
                    lfs_file.write(src_file.read())
        elif filename.is_dir():
            fs.mkdir(lfs_fname)
    # verify

    print(f"write filesystem to {target}")
    with open(target, "wb") as fh:
        fh.write(fs.context.buffer)


#


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


# rp2_common
FLASH_PAGE_SIZE = 256
FLASH_SECTOR_SIZE = 4096  # :=> LittleFS Block
# FLASH_BLOCK_SIZE = 65536


port_info_list: List[PortDiskInfo] = [
    PortDiskInfo("esp32-generic", 256, 4096, 512),
    PortDiskInfo("esp8266-generic", 256, 4096, 512),
    PortDiskInfo("rp2-pico", 256, 4096, 352),  # pico  = 0x100a0000-0x10200000 (1408K):
    # PortDiskInfo("pico_w", 256, 4096, 208),
    # PortDiskInfo("pimoroni_picolipo_16mb", 256, 4096, 3840), # 0x10100000-0x11000000 (15360K)
    # PortDiskInfo("SAMD", 1536, 4096, 512),
]
# PICO_LIPO_16
# ports\rp2\boards\PIMORONI_PICOLIPO_16MB\mpconfigboard.h
# define MICROPY_HW_FLASH_STORAGE_BYTES (15 * 1024 * 1024) 0x00F0_0000


def main(port_name: str):
    port_info = next((p for p in port_info_list if p.name.lower() == port_name.lower()), None)
    if not port_info:
        print(f"Port {port_name} not found")
        return

    page_size = port_info.page_size
    block_size = port_info.block_size
    block_count = port_info.block_count
    image_size = port_info.image_size
    print(f"Port: {port_name}, PageSize: {page_size}, BlockSize: {block_size}, BlockCount: {block_count}, ImageSize: {int(image_size/1024)}Kb")

    # location of workspace
    workspace_dir = Path(__file__).parent.parent.absolute()

    # where are artefacts compared to workspace
    build_pth = workspace_dir / "build"
    build_pth.mkdir(parents=True, exist_ok=True)
    littlefs_image = build_pth / "littlefs.img"
    # create littlefs
    folder_to_lfs(
        source=f"{workspace_dir}/src",
        target=str(littlefs_image),
        disk_version=VFS_LFS2,
        block_size=block_size,
        block_count=block_count,
        prog_size=page_size,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", "--port-board", help="the name of the port and board to build for (rp2-pico, esp32-generic)")
    args = parser.parse_args()
    port = args.port or os.environ.get("PORT_BOARD") or "esp32-generic"
    main(port)
