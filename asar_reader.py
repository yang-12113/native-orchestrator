"""Read-only extraction of installed Electron archive entries for compatibility diagnostics."""
import argparse
import json
import struct
from pathlib import Path

class Asar:
    def __init__(self, path):
        self.path = Path(path)
        with self.path.open("rb") as stream:
            prefix = stream.read(16)
            _, header_size, _, json_size = struct.unpack("<IIII", prefix)
            self.header = json.loads(stream.read(json_size))
        self.base = 8 + header_size
    def entries(self, node=None, prefix=""):
        node = self.header if node is None else node
        for name, value in node.get("files", {}).items():
            path = prefix+name
            if "files" in value:
                yield from self.entries(value,path+"/")
            else:
                yield path,value
    def read(self, name):
        node = self.header
        for part in name.split("/"):
            node = node["files"][part]
        if node.get("unpacked"):
            return Path(str(self.path)+".unpacked").joinpath(*name.split("/")).read_bytes()
        with self.path.open("rb") as stream:
            stream.seek(self.base+int(node["offset"]))
            return stream.read(node["size"])

if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("path")
    p.add_argument("--read")
    p.add_argument("--match",default="main|auth|config|provider|preference|storage")
    args=p.parse_args()
    archive=Asar(args.path)
    if args.read:
        import sys
        sys.stdout.buffer.write(archive.read(args.read))
    else:
        import re
        matches=[{"path":name,"bytes":value.get("size")} for name,value in archive.entries() if re.search(args.match,name,re.I)]
        print(json.dumps(matches[:80],ensure_ascii=True))
