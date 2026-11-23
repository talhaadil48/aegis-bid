import argparse
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    args = parser.parse_args()
    path = Path(args.directory)
    path.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    with (path / "audit-private.pem").open("xb") as f:
        f.write(
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
    (path / "audit-private.pem").chmod(0o600)
    with (path / "audit-public.pem").open("xb") as f:
        f.write(
            key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        )
    print("Keep private key outside source control. Distribute public key through an independent trusted channel.")


if __name__ == "__main__":
    main()
