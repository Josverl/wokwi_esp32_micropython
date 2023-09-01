import argparse
import os
import platform
import subprocess
from pathlib import Path

from create_littlefs import folder_to_lfs
from diskportinfo import port_info_list
from uf2_merge import merge_uf2_littlefs


def get_disk_info(port: str):
    """Return the disk info for the given port name."""
    for port_info in port_info_list:
        if port_info.name == port:
            return port_info
    port = f"{port}-generic"
    for port_info in port_info_list:
        if port_info.name == port:
            return port_info
    return None


def esptool_merge(output_bin: Path, firmware_bin: Path, littlefs_img: Path, flash_size="4MB"):
    """\
    Merge the firmware and littlefs image into a single binary.
    
    The merge_bin command will merge multiple binary files (of any kind) into a single file that can be flashed to a device later.
    Any gaps between the input files are padded with 0xFF bytes

    https://docs.espressif.com/projects/esptool/en/latest/esp32/esptool/basic-commands.html?highlight=merge_bin#merge-binaries-for-flashing-merge-bin
    """

    command = [
        "esptool",
        "--chip",
        "esp32",
        "merge_bin",
        "-o",
        output_bin,
        "--flash_mode",
        "dio",
        "--flash_size",
        flash_size,
        "0x1000",
        firmware_bin,
        "0x200000",
        littlefs_img,
    ]
    try:
        subprocess.run(command, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")
        return False


def firmware_port(port: str, firmware_path: Path):
    if port == "auto":
        port = firmware_path.stem.split("-")[0] or "-"
        if port.endswith("spiram"):
            port = port[:-6]
    ver = firmware_path.stem.split("-")[-1] or "-"

    return port


def main(source_path: Path, firmware_path: Path, port: str, build_path: Path):
    # get information on the port and firmware as that is needed to size the littlefs image correctly

    port = firmware_port(port, firmware_path)

    print("Source folder path:", source_path)
    print("Firmware path:", firmware_path)
    print("Micropython Port:", port)

    disk_info = get_disk_info(port)
    if not disk_info:
        print(f"Port {port} not found")
        return
    # create littlefs image for this port
    littlefs_image = build_path / "littlefs.img"
    print(f"Create littlefs image: {littlefs_image}")

    try:
        folder_to_lfs(
            source=str(source_path),
            target=str(littlefs_image),
            disk_version=disk_info.vfstype,
            block_size=disk_info.block_size,
            block_count=disk_info.block_count,
        )
    except Exception as e:
        print(f"Error: {e}")
        return
    # now merge the firmware and littlefs image into a single binary
    # this is different for each finary format
    if port.startswith("esp32"):
        esptool_merge(
            firmware_bin=firmware_path,
            littlefs_img=littlefs_image,
            output_bin=build_path / "firmware_lfs.bin",
        )
    elif port.startswith("rp2"):
        merge_uf2_littlefs(
            firmware_uf2=firmware_path,
            littlefs_img=littlefs_image,
            out_path=build_path / "firmware_lfs.uf2",
            save_littlefs=True,
            chunk_size=256,
        )


def parse_cmdline():
    parser = argparse.ArgumentParser(description="Merse source code and firmware into a single file.")
    parser.add_argument("--port", type=str, help="port", default=os.environ.get("PORT", "auto"))
    parser.add_argument("--source", type=str, help="source folder path", default="./src")
    parser.add_argument("--firmware", type=str, help="firmware path", default="auto")
    parser.add_argument("--build", type=str, help="build folder", default="./build")

    args = parser.parse_args()
    args.source = Path(args.source)
    args.build = Path(args.build)
    if args.firmware == "auto":
        prefix = args.port if args.port != "auto" else ""
        args.firmware = next(Path("./firmware").glob(f"{prefix}*"))
    else:
        args.firmware = Path(args.firmware)
    return args


if __name__ == "__main__":
    args = parse_cmdline()
    main(args.source, args.firmware, args.port, args.build)
