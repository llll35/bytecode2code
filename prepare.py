#!/usr/bin/env python3
"""Download CPython embeddable builds 3.9-3.15 into embed_python/."""
import os, sys, urllib.request, zipfile, tempfile, time

VERSIONS = ("3.9", "3.10", "3.11", "3.12", "3.13", "3.14", "3.15")
ARCH = os.environ.get("PYTHON_ARCH", "amd64")  # amd64 or win32

# Common patch versions for these minor releases (update as needed)
PATCH_MAP = {
    "3.9":  "3.9.21",
    "3.10": "3.10.16",
    "3.11": "3.11.11",
    "3.12": "3.12.10",
    "3.13": "3.13.9",
    "3.14": "3.14.0",
    "3.15": "3.15.0",
}

def url_for(ver):
    patch = PATCH_MAP.get(ver, ver)
    return (
        f"https://www.python.org/ftp/python/{patch}/"
        f"python-{patch}-embed-{ARCH}.zip"
    )

def main():
    root = os.path.dirname(os.path.abspath(__file__))
    embed = os.path.join(root, "embed_python")
    os.makedirs(embed, exist_ok=True)

    for ver in VERSIONS:
        folder = os.path.join(embed, f"python-{ver}")
        exe = os.path.join(folder, "python.exe")
        if os.path.isfile(exe):
            print(f"  [{ver}] already present -> skip")
            continue

        url = url_for(ver)
        zip_path = os.path.join(embed, f"python-{ver}.zip")
        print(f"[{ver}] downloading {url} ...")
        try:
            urllib.request.urlretrieve(url, zip_path)
        except Exception as exc:
            print(f"  [{ver}] download failed: {exc}")
            # try win32 fallback
            alt_url = url.replace("amd64", "win32")
            try:
                urllib.request.urlretrieve(alt_url, zip_path)
                print(f"  [{ver}] fallback win32 OK")
            except Exception as exc2:
                print(f"  [{ver}] fallback also failed: {exc2}")
                continue

        print(f"  [{ver}] extracting -> {folder}")
        os.makedirs(folder, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(folder)

        # Some embeddable zips contain a subfolder; flatten if needed
        # (e.g. python-3.9.21/ inside the zip -> should end in python-3.9/)
        # We assume extractall puts contents directly into folder; if there's
        # an inner folder named python-X.Y/ we could flatten further.
        inner = [d for d in os.listdir(folder) if os.path.isdir(os.path.join(folder, d)) if d.startswith("python-")]
        # No automatic flatten needed for standard embeddable layout.

        # Remove zip after success
        try:
            os.remove(zip_path)
        except OSError:
            pass
        print(f"  [{ver}] done")

    print("Finished. Verify with: python main.py info")

if __name__ == "__main__":
    main()
