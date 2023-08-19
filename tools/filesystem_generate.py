from pathlib import Path

from littlefs import LittleFS

VFS_LFS1 =  0x0001_0000
VFS_LFS2 =  0x0002_0000

VFLASH_BLOCK_SIZE = 4096

def folder_to_lfs(folder: str = "./src", image: str = "./littlefs.img", disk_version: int = VFS_LFS2) :
    """
    Create Little FS image with the contents of the folder.

    Parameters:
    - folder: source folder to wrap
    - image: destination image file
    - disk_version: LittleFS File System Version 0x0002_0000 needed by micropython builds @v1.20.0
    """
    fs = LittleFS(
        block_size=VFLASH_BLOCK_SIZE, block_count=512, prog_size=256, disk_version=disk_version
    )
    source_path = Path(folder)
    print(f"Create new filesystem from {source_path}")
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

    print(f"write filesystem to {image}")
    with open(image, "wb") as fh:
        fh.write(fs.context.buffer)


# location of workspace
workspace_dir = Path(__file__).parent.parent.absolute()

# where are artefacts compared to workspace
build_pth = workspace_dir / "build"
build_pth.mkdir(parents=True, exist_ok=True)
littlefs_image = build_pth / "littlefs.img"

# create littlefs
folder_to_lfs(f"{workspace_dir}/src", str(littlefs_image))
