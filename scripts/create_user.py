"""Provision an account from a trusted operator shell."""

import argparse
from getpass import getpass

from pydantic import ValidationError

from aegis.auth import NewAccount, create_account


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("--role", choices=("bidder", "seller", "auditor", "admin"), required=True)
    args = parser.parse_args()
    password = getpass("Password: ")
    if password != getpass("Confirm password: "):
        parser.error("Passwords do not match.")
    try:
        account = NewAccount(username=args.username, password=password)
    except ValidationError:
        parser.error("Use a 3–32 character username (letters, digits, _ or -) and a 12–128 character password.")
    if create_account(account, role=args.role) is None:
        parser.error("Username is unavailable.")
    print(f"Created {args.role} account {account.username}.")


if __name__ == "__main__":
    main()
