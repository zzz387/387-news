"""Owner-only review envelope. Never uses a production or Gemini key."""
import base64
import hashlib
import json
import secrets
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa,padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

FORMAT='387-owner-review-v1'
LABEL=b'387-owner-review-key-v1'


def public_key(encoded):
    if not isinstance(encoded,str) or len(encoded)>2048: raise ValueError('OWNER_PUBLIC_KEY_INVALID')
    raw=base64.b64decode(encoded,validate=True)
    key=serialization.load_der_public_key(raw)
    if not isinstance(key,rsa.RSAPublicKey) or not 3072<=key.key_size<=4096 or key.public_numbers().e!=65537:
        raise ValueError('OWNER_RSA_3072_OR_4096_REQUIRED')
    return key,hashlib.sha256(raw).hexdigest()


def encode_public(key):
    return base64.b64encode(key.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).decode()


def seal(data,recipient,date,commit):
    key,fingerprint=public_key(recipient)
    metadata={'format':FORMAT,'key_id':fingerprint,'issue_date':date,'commit':commit}
    aad=json.dumps(metadata,sort_keys=True,separators=(',',':')).encode()
    content_key=secrets.token_bytes(32); nonce=secrets.token_bytes(12)
    wrapped=key.encrypt(content_key,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=LABEL))
    return json.dumps({'metadata':metadata,'wrapped_key':base64.b64encode(wrapped).decode(),
        'nonce':base64.b64encode(nonce).decode(),
        'ciphertext':base64.b64encode(AESGCM(content_key).encrypt(nonce,data,aad)).decode()},separators=(',',':')).encode()


def open_bundle(blob,private_key,expected_commit,expected_date):
    envelope=json.loads(blob); metadata=envelope['metadata']
    if (metadata.get('format')!=FORMAT or metadata.get('commit')!=expected_commit
            or metadata.get('issue_date')!=expected_date): raise ValueError('OWNER_BUNDLE_PROVENANCE_MISMATCH')
    _,fingerprint=public_key(encode_public(private_key.public_key()))
    if metadata.get('key_id')!=fingerprint: raise ValueError('OWNER_BUNDLE_RECIPIENT_MISMATCH')
    key=private_key.decrypt(base64.b64decode(envelope['wrapped_key'],validate=True),
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=LABEL))
    aad=json.dumps(metadata,sort_keys=True,separators=(',',':')).encode()
    return AESGCM(key).decrypt(base64.b64decode(envelope['nonce'],validate=True),
        base64.b64decode(envelope['ciphertext'],validate=True),aad)
