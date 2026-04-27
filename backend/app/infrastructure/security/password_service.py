import base64
import hashlib
import hmac
import os


# 密码哈希配置。
# 这里使用 Python 标准库中的 PBKDF2-HMAC，
# 在当前环境无法安装额外依赖时也能完成安全的密码存储。
ITERATIONS = 100_000


def hash_password(password: str) -> str:
    """对明文密码做哈希，并返回可直接存库的完整字符串。"""
    salt = os.urandom(16)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        ITERATIONS,
    )
    return (
        f"pbkdf2_sha256${ITERATIONS}$"
        f"{base64.b64encode(salt).decode('utf-8')}$"
        f"{base64.b64encode(derived_key).decode('utf-8')}"
    )


def verify_password(plain_password: str, password_hash: str) -> bool:
    """校验明文密码和数据库中保存的 PBKDF2 哈希是否匹配。"""
    try:
        algorithm, iterations, salt_b64, hash_b64 = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False

        salt = base64.b64decode(salt_b64.encode("utf-8"))
        expected_hash = base64.b64decode(hash_b64.encode("utf-8"))
        derived_key = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt,
            int(iterations),
        )
        return hmac.compare_digest(derived_key, expected_hash)
    except Exception:
        return False
