"""Generate a development signing certificate for C2PA (task 3.11).

    python -m scripts.make_signing_cert --out ~/.persona-studio/c2pa

**What this produces is valid, not trusted.** A manifest signed with it verifies as
`validation_state: Valid` — the file has not been altered since signing — but it does not
chain to an authority on the C2PA trust list, so no verifier will call it trusted.
Amendment A9 flagged that as procurement with lead time; this exists so the pipeline can
be built and tested while that happens, not as a substitute for it.

**Why a chain and not one self-signed certificate.** The C2PA certificate profile wants an
end-entity certificate issued by a CA. A lone self-signed certificate is refused by the
library with "the certificate is invalid", which is true and tells you nothing. So this
makes a small root and issues a signing certificate under it.

**The key is a secret.** It is written with owner-only permissions and must not be
committed, nor live anywhere backed up casually. In production it belongs in a KMS or an
HSM, which the C2PA bindings support through a callback signer.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

CA_CONFIG = """[req]
distinguished_name=dn
prompt=no
[dn]
CN={name} Development Root
O={org}
C={country}
[v3]
basicConstraints=critical,CA:TRUE,pathlen:0
keyUsage=critical,keyCertSign,cRLSign
"""

# emailProtection is the extended key usage the C2PA certificate profile expects for
# document signing. Deliberately NOT marked critical: a critical EKU on the end-entity
# certificate is stricter than the profile requires and invites verifier disagreement.
EE_CONFIG = """[req]
distinguished_name=dn
prompt=no
[dn]
CN={name} Signing
O={org}
C={country}
[v3]
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature
extendedKeyUsage=emailProtection
"""


def run(*args: str) -> None:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"{args[0]} failed: {result.stderr.strip()[:400]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="directory to write into")
    parser.add_argument("--name", default="Persona Studio")
    parser.add_argument("--org", default="Persona Studio")
    parser.add_argument("--country", default="GB")
    parser.add_argument("--days", type=int, default=365)
    args = parser.parse_args()

    out = args.out.expanduser()
    out.mkdir(parents=True, exist_ok=True)
    fields = {"name": args.name, "org": args.org, "country": args.country}
    (out / "ca.cnf").write_text(CA_CONFIG.format(**fields))
    (out / "ee.cnf").write_text(EE_CONFIG.format(**fields))

    # Root.
    run(
        "openssl",
        "ecparam",
        "-name",
        "prime256v1",
        "-genkey",
        "-noout",
        "-out",
        str(out / "ca.key.pem"),
    )
    run(
        "openssl",
        "req",
        "-new",
        "-x509",
        "-key",
        str(out / "ca.key.pem"),
        "-sha256",
        "-days",
        str(args.days * 10),
        "-out",
        str(out / "ca.pem"),
        "-config",
        str(out / "ca.cnf"),
        "-extensions",
        "v3",
    )

    # End entity. PKCS#8, because the library refuses a SEC1 EC key with an error about
    # the PEM type label.
    run(
        "openssl",
        "ecparam",
        "-name",
        "prime256v1",
        "-genkey",
        "-noout",
        "-out",
        str(out / "ee.sec1.pem"),
    )
    run(
        "openssl",
        "pkcs8",
        "-topk8",
        "-nocrypt",
        "-in",
        str(out / "ee.sec1.pem"),
        "-out",
        str(out / "key.pem"),
    )
    (out / "ee.sec1.pem").unlink()
    run(
        "openssl",
        "req",
        "-new",
        "-key",
        str(out / "key.pem"),
        "-out",
        str(out / "ee.csr"),
        "-config",
        str(out / "ee.cnf"),
    )
    run(
        "openssl",
        "x509",
        "-req",
        "-in",
        str(out / "ee.csr"),
        "-CA",
        str(out / "ca.pem"),
        "-CAkey",
        str(out / "ca.key.pem"),
        "-CAcreateserial",
        "-days",
        str(args.days),
        "-sha256",
        "-extfile",
        str(out / "ee.cnf"),
        "-extensions",
        "v3",
        "-out",
        str(out / "ee.pem"),
    )

    # End-entity FIRST, then its issuer. The other order is rejected.
    chain = out / "chain.pem"
    chain.write_bytes((out / "ee.pem").read_bytes() + (out / "ca.pem").read_bytes())
    for secret in (out / "key.pem", out / "ca.key.pem"):
        secret.chmod(0o600)

    print(f"chain  {chain}")
    print(f"key    {out / 'key.pem'}  (secret, mode 600)")
    print("\nPoint the pipeline at them:")
    print(f"  export C2PA_SIGN_CERT={chain}")
    print(f"  export C2PA_SIGN_KEY={out / 'key.pem'}")
    print("\nThis signs as VALID, not TRUSTED. A trusted manifest needs a certificate")
    print("from an authority on the C2PA trust list — amendment A9, procurement.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
