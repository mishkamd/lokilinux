"""lokilinux-ca-signer — isolated CA signing microservice.

Runs as a separate process/container that alone can read the CA private
key (`CA_KEY_PATH`, mounted nowhere else). Reachable only over a Unix
domain socket — this process has no network stack at all
(`network_mode: "none"` in docker-compose). One verb: sign an agent's
public key into a short-lived mTLS client cert. api/grpc call this
instead of touching ca.key directly.

Run: uvicorn lokilinux.services.ca_signer_service:app --uds <CA_SIGNER_SOCKET_PATH>
"""

import datetime
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

CA_KEY_PATH = os.environ.get("CA_KEY_PATH", "/etc/lokilinux/ca-key/ca.key")
CA_CERT_PATH = os.environ.get("CA_CERT_PATH", "/etc/lokilinux/certs/ca.crt")
# CA/Browser Forum leaf-cert ceiling — generous headroom over our 30/365 day uses,
# just a sanity bound against a caller passing an absurd value.
MAX_VALIDITY_DAYS = 397

_ca_key: Optional[RSAPrivateKey] = None
_ca_cert: Optional[x509.Certificate] = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _ca_key, _ca_cert
    with open(CA_KEY_PATH, "rb") as f:
        _ca_key = serialization.load_pem_private_key(f.read(), password=None)
    with open(CA_CERT_PATH, "rb") as f:
        _ca_cert = x509.load_pem_x509_certificate(f.read())
    yield
    _ca_key = None
    _ca_cert = None


app = FastAPI(
    title="lokilinux-ca-signer",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


class SignRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=255)
    public_key_pem: str = Field(min_length=1, max_length=8192)
    validity_days: int = Field(gt=0, le=MAX_VALIDITY_DAYS)


class SignResponse(BaseModel):
    cert_pem: str


@app.post("/sign", response_model=SignResponse)
def sign(body: SignRequest) -> SignResponse:
    if _ca_key is None or _ca_cert is None:
        raise HTTPException(status_code=503, detail="ca signer not ready")

    try:
        public_key = serialization.load_pem_public_key(body.public_key_pem.encode())
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid public_key_pem")

    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, body.agent_id),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "LokiLinux"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(_ca_cert.subject)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=body.validity_days))
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )
        .sign(_ca_key, hashes.SHA256())
    )
    return SignResponse(cert_pem=cert.public_bytes(serialization.Encoding.PEM).decode())


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": _ca_key is not None}
