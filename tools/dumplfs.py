#!/usr/bin/python3

PRODUCT = "Dump LittleFS File Systems"
PROGRAM = "dumplfs.py"
VERSION = "3.02"
CREATED = "hippy"
LICENSE = "MIT Licensed"
DETAILS = "https://opensource.org/licenses/MIT"

import os
import sys

try:
  from littlefs import LittleFS
except:
  print("You first need to run 'pip3 install littlefs-python'")
  sys.exit()

def Size(total, scale=1):
  s = "{:,}".format(total * 1.0 /scale)
  while s.endswith("0"):
    s = s[:-1]
  if s.endswith("."):
    s = s[:-1]
  return s

def MkDir(path, up=0, what="Path"):
  while up > 0:
    path = path[:path.rfind("/")]
    up -= 1
  print("  Creating {} {}".format(what, path))
  if not os.path.isdir(path):
    path += "/"
    for n in range(len(path)):
      if path[n] == "/":
        if not os.path.isdir(path[:n]):
          os.mkdir(path[:n])

def Main():

  # Determine where the binary image is

  if len(sys.argv) <= 1 : filename = "everything.bin"
  else                  : filename = sys.argv[1]
  if not os.path.isfile(filename):
    print("No '{}' found".format(filename))
    return

  # Load the actual image

  print("Loading '{}'".format(filename))
  with open(filename, "rb") as f:
    bin_img = f.read()

  # Determine the size of the image and report it

  def Fix(b, n=1):
    s = "{:,}".format(b * 1.0 / n)
    while s.endswith("0"):
      s = s[:-1]
    if s.endswith("."):
      s = s[:-1]
    return s

  b  = Size(len(bin_img))
  kb = Size(len(bin_img), 1024)
  mb = Size(len(bin_img), 1024 * 1024)
  print("  {} bytes, {} KB, {} MB".format(b, kb, mb))

  # Check if image is valid

  if not mb in ["2", "4", "8", "16"]:
    print("File is not a valid MB size")
    return

  # Checksum the first block to verify it's from an RP2040

  def Byte(n):
    if n >= len(bin_img) : return 0
    else             : return bin_img[n]

  def Word(n):
    return Byte(n + 1) << 8 | Byte(n)

  def Quad(n):
    return (Word(n + 2) << 16) | Word(n)

  def Crc32(crc, byt):
    byt = byt << 24
    for bitNumber in range(8):
      if (crc ^ byt) & 0x80000000 : polynomial = 0x4C11DB7
      else                        : polynomial = 0
      crc = ((crc & 0x7FFFFFFF) << 1) ^ polynomial
      byt = ((byt & 0x7FFFFFFF) << 1)
    return crc

  crc32 = 0xFFFFFFFF
  for adr in range(256-4):
    crc32 = Crc32(crc32, Byte(adr))

  if crc32 != Quad(256-4):
    print("Not a valid RP2040 image")
    # return

  # See if there are any expected file systems

  print("Looking for expected LittleFS file systems")

  known = {}
  where = []
  for s in os.popen("picotool info -a {}".format(filename)).read().strip().split("\n"):
    # embedded drive: 0x1012c000-0x10200000 (848K): MicroPython
    if s.strip().startswith("embedded drive:"):
      a = s.split()
      #  0           1         2                        3         4
      # "embedded", "drive:", "0x1012c000-0x10200000", "(848K):", "MicroPython"
      adr = int(a[2][:a[2].find("-")], 16)
      siz = int(a[3][1:-3]) * 1024
      nam = " ".join(a[4:]).strip()
      if siz % 4096 == 0:
        if adr >= 0x10000000 and adr < 0x10200000:
          where.append(adr - 0x10000000 + 4)
          if nam == "":
            print("  0x{:08X}".format(adr))
          else:
            known[adr - 0x10000000] = nam
            print("  0x{:08X} : {}".format(adr, nam))

  # Also look in the '.drives' file if there is one

  if os.path.isfile(filename + ".drives"):
    with open(filename + ".drives", "r") as f:
      for s in f:
        a = s.strip().split()
        if len(a) >= 2:
          #  0             1
          # "0x1012c000", "MicroPython"
          adr = int(a[0],16)
          nam = " ".join(a[1:]).strip()
          if adr >= 0x10000000 and adr < 0x10200000:
            if (adr % 4096) == 0:
              if not (adr - 0x10000000 + 4) in where:
                where.append(adr - 0x10000000 + 4)
                known[adr - 0x10000000] = nam
                print("  0x{:08X} : {}".format(adr, nam))
              elif (not (adr - 0x1000000) in known) or \
                   (known[adr - 0x10000000] != nam):
                known[adr - 0x10000000] = nam
                print("  0x{:08X} : {}".format(adr, nam))

  if len(where) == 0:
    print("  None")

  # Scan the image for LittleFS file system markers

  magic = b'\xF0\x0F\xFF\xF7littlefs/\xE0\x00\x10'
  def Match(adr):
    for n in range(len(magic)):
      if adr+n >= len(bin_img) or bin_img[adr+n] != magic[n]:
        return False
    return True

  def MakeFileNames(filename, adr, prefix, nam):
    n = filename.rfind("/")
    if n >= 0:
      filename = filename[n+1:]
    n = filename.find(".")
    if n >= 0:
      filename = filename[:n]
    if adr in known : sub = known[adr]
    else            : sub = "{:08X}".format(adr + 0x10000000)
    src = prefix + "/" + nam
    shw = src[1:]
    dst = "./extracted/{}/{}{}".format(filename, sub, shw).rstrip("/")
    return shw, src, dst

  if len(where) == 0:
    print("Looking for LittleFS file system markers")
    where = range(4, len(bin_img))
  else:
    print("Checking expected LittleFS file systems")

  found = []
  for adr in where:
    if Match(adr):
      adr = adr - 4
      # The LittleFS marker must be on a 4K boundary
      if adr % 4096 == 0:
        # We read the file system size
        block = Quad(adr + 24)
        count = Quad(adr + 28)
        sized = block * count
        # Blocks must be 4K sized
        if block == 4096:
          # Check the file system fits flash available for it
          if sized <= len(bin_img) - adr:
           # Not a file system if a duplicated super block which follows an
           # actual super block
           if len(found) == 0 or adr != found[-1][0] + 4096:
              # See if we can mount the file system
              fs = LittleFS(block_size=block, block_count=count, mount=False)
              fs.context.buffer = bin_img[adr:]
              try:
                fs.mount()
                if adr in known:
                  print("  0x{:08X} : {}".format(adr + 0x10000000, known[adr]))
                else:
                  print("  0x{:08X}".format(adr + 0x10000000))
                b  = Size(sized)
                kb = Size(sized, 1024)
                mb = Size(sized, 1024 * 1024)
                print("    {} bytes, {} KB, {} MB, {} x {}".format(
                      b, kb, mb,
                      count, block))
                fileCount = 0
                for item in fs.walk("."):
                  fileCount += len(item[1]) + len(item[2])
                found.append([adr, b, kb, mb, count, block, fileCount])
                if fileCount > 0:
                  s, src, dst = MakeFileNames(filename, adr, ".", "")
                  print("      Found Path {}".format(s))
                  for item in fs.walk("."):
                    for this in item[1]:
                      s, src, dst = MakeFileNames(filename, adr, item[0], this)
                      print("      Found Path {}".format(s))
                  for item in fs.walk("."):
                    for this in item[2]:
                      s, src, dst = MakeFileNames(filename, adr, item[0], this)
                      print("      Found File {}".format(s))
              except:
                pass

  if len(found) == 0:
    print("No LittleFS file system found")
    return

  print("Viable LittleFS file systems")
  any = 0
  for adr, b, kb, mb, count, block, fileCount in found:
    any += fileCount
    if   fileCount == 0 : desc = "Not used"
    else                : desc = "{} items".format(fileCount + 1)
    print("  0x{:08X} : {} bytes, {} KB, {} MB\t{:>5} x {}, {}".format(
          adr + 0x10000000,
          b, kb, mb,
          count, block,
          desc))

  # If we have named this program as "listlfs.py" or similar then we don't
  # extract the files.

  if sys.argv[0].lower().find("list") >= 0:
    if any == 0:
      print("No files found on any file systems")
    return

  # Extract the files

  if any == 0:
    print("Nothing found to extract from file systems")
    return

  print("Extracting files")
  first = True
  for adr, b, kb, mb, count, block, fileCount in found:
    if fileCount > 0:
      fs = LittleFS(block_size=block, block_count=count, mount=False)
      fs.context.buffer = bin_img[adr:]
      fs.mount()
      s, src, dst = MakeFileNames(filename, adr, ".", "/")
      if first:
        MkDir(dst, 2, "Root")
        MkDir(dst, 1, "Dump")
        first = False
      MkDir(dst)
      for item in fs.walk("."):
        for this in item[1]:
          s, src, dst = MakeFileNames(filename, adr, item[0], this)
          MkDir(dst)
      for item in fs.walk("."):
        for this in item[2]:
          s, src, dst = MakeFileNames(filename, adr, item[0], this)
          print("  Creating File {}".format(dst))
          try:
            with fs.open(src, "rb") as fSrc:
               with open(dst, "wb") as fDst:
                 fDst.write(fSrc.read())
          except:
             print("    Failed")

if __name__ == "__main__":
  Main()
