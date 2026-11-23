"""Download checksum-verified local tools; never changes the user's kubeconfig."""

import hashlib
import platform
import urllib.request
from pathlib import Path


def main():
    system = "windows" if platform.system() == "Windows" else "linux"
    suffix = ".exe" if system == "windows" else ""
    root = Path(".tools")
    root.mkdir(exist_ok=True)
    artifacts = {
        "kind": (
            f"https://github.com/kubernetes-sigs/kind/releases/download/v0.30.0/kind-{system}-amd64",
            ".sha256sum",
        ),
        "kubectl": (f"https://dl.k8s.io/release/v1.34.0/bin/{system}/amd64/kubectl{suffix}", ".sha256"),
    }
    for name, (url, checksum_suffix) in artifacts.items():
        checksum = urllib.request.urlopen(url + checksum_suffix, timeout=60).read().decode().split()[0]
        path = root / (name + suffix)
        if not path.exists():
            temporary = path.with_suffix(".download")
            urllib.request.urlretrieve(url, temporary)
            if hashlib.file_digest(temporary.open("rb"), "sha256").hexdigest() != checksum:
                raise ValueError("Tool checksum mismatch: " + name)
            temporary.replace(path)
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != checksum:
                raise ValueError("Existing tool checksum mismatch: " + name)
        path.chmod(0o755)
        print(name + ": verified " + checksum)


if __name__ == "__main__":
    main()
