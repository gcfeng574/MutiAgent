from pymysql.cursors import DictCursor

from infrastructure.database.database_pool import pool


class UserRepository:
    """用户与 refresh token 的数据库访问层。"""

    def get_user_by_username(self, username: str):
        """根据唯一用户名查询用户记录。"""
        connection = pool.connection()
        cursor = connection.cursor(DictCursor)
        try:
            cursor.execute("SELECT * FROM users WHERE username=%s LIMIT 1", (username,))
            return cursor.fetchone()
        finally:
            cursor.close()
            connection.close()

    def get_user_by_id(self, user_id: int):
        """根据主键 id 查询用户记录。"""
        connection = pool.connection()
        cursor = connection.cursor(DictCursor)
        try:
            cursor.execute("SELECT * FROM users WHERE id=%s LIMIT 1", (user_id,))
            return cursor.fetchone()
        finally:
            cursor.close()
            connection.close()

    def create_user(self, username: str, email: str, password_hash: str):
        """插入新用户，并返回新创建的用户 id。"""
        connection = pool.connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO users (username, email, password_hash, is_active, role)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (username, email, password_hash, True, "user"),
            )
            connection.commit()
            return cursor.lastrowid
        finally:
            cursor.close()
            connection.close()

    def save_refresh_token(self, user_id: int, token_hash: str, expires_at):
        """保存 refresh token 的哈希值，便于后续轮换或吊销。"""
        connection = pool.connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO user_refresh_tokens (user_id, token_hash, expires_at, revoked)
                VALUES (%s, %s, %s, %s)
                """,
                (user_id, token_hash, expires_at, False),
            )
            connection.commit()
        finally:
            cursor.close()
            connection.close()

    def get_refresh_token(self, token_hash: str):
        """根据 refresh token 的哈希值查询记录。"""
        connection = pool.connection()
        cursor = connection.cursor(DictCursor)
        try:
            cursor.execute(
                "SELECT * FROM user_refresh_tokens WHERE token_hash=%s LIMIT 1",
                (token_hash,),
            )
            return cursor.fetchone()
        finally:
            cursor.close()
            connection.close()

    def revoke_refresh_token(self, token_hash: str):
        """将 refresh token 标记为已吊销。"""
        connection = pool.connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                "UPDATE user_refresh_tokens SET revoked=1 WHERE token_hash=%s",
                (token_hash,),
            )
            connection.commit()
        finally:
            cursor.close()
            connection.close()


user_repository = UserRepository()
