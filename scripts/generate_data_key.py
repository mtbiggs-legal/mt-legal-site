"""Print a new DATA_ENCRYPTION_KEY for .env.

Usage:
    python scripts/generate_data_key.py

Put the printed line in .env AND store a copy somewhere outside this folder
(password manager, printed in the office safe). If the key is lost, encrypted
client records cannot be recovered.
"""

from cryptography.fernet import Fernet

if __name__ == "__main__":
    print(f"DATA_ENCRYPTION_KEY={Fernet.generate_key().decode()}")
    print("\nAdd the line above to .env and back the key up OUTSIDE this folder.")
