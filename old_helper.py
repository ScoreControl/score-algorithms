import os
import zipfile

mscz_path = "./msczs/tbd-ss-8-12.mscz"
extract_dir = "./extracted/tbd-ss-8-12"

with zipfile.ZipFile(mscz_path, "r") as archive:
  for file_name in archive.namelist():
    archive.extract(file_name, extract_dir)
    mscx_path = os.path.join(extract_dir, file_name)
    print(f"Extracted MSCX to: {mscx_path}")

