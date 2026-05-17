"""
Interactive Ring auth flow — acquires a refresh token and stores it
directly in the housepanel-ring-secrets K8s Secret.

Usage:
    python scripts/get_token.py

The token value is never printed to stdout.
"""
import asyncio
import getpass
import subprocess
import sys


async def main() -> None:
    try:
        from ring_doorbell import Auth, Requires2FAError
    except ImportError:
        print("ring_doorbell not installed. Run: pip install 'ring_doorbell[listen]'")
        sys.exit(1)

    print("=== Ring Token Acquisition ===")
    email = input("Ring email: ")
    password = getpass.getpass("Ring password: ")

    auth = Auth("HousePanel/0.1", None, lambda token: None)
    try:
        await auth.async_fetch_token(email, password)
    except Requires2FAError:
        otp = input("2FA code: ")
        await auth.async_fetch_token(email, password, otp)

    refresh_token = auth._token["refresh_token"]

    # Close the underlying aiohttp session to suppress resource warnings
    if hasattr(auth, "_session") and auth._session is not None:
        await auth._session.close()

    # Store directly in K8s — token value never printed
    result = subprocess.run(
        [
            "kubectl", "create", "secret", "generic", "housepanel-ring-secrets",
            "--namespace", "housepanel",
            f"--from-literal=RING_REFRESH_TOKEN={refresh_token}",
            "--dry-run=client", "-o", "yaml",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR generating secret manifest: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    apply = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=result.stdout,
        capture_output=True,
        text=True,
    )
    if apply.returncode != 0:
        print(f"ERROR applying secret: {apply.stderr}", file=sys.stderr)
        sys.exit(1)

    print("✓ housepanel-ring-secrets created/updated in namespace housepanel")
    print("✓ Token stored. You can now deploy the ring-integration service.")


if __name__ == "__main__":
    asyncio.run(main())
