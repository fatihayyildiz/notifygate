"""Hermes hooks.outbound imza doğrulaması.

Hermes, secret yapılandırıldığında payload'ı HMAC-SHA256 ile imzalar:
  X-Hermes-Signature-256: sha256=<hexdigest>
GitHub webhook'larıyla aynı format. Secret yoksa legacy davranış:
imza kontrolü atlanır (lokal geliştirme).
"""
import hashlib
import hmac

from .config import settings


def verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    secret = settings.hermes_secret
    if not secret:
        return True  # secret yapılandırılmadı → legacy davranış

    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature_header[len("sha256="):], expected)
