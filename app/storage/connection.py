import psycopg2
import psycopg2.extras
import os
from dotenv import load_dotenv
from app.utils.logger import Logger

load_dotenv()


class ConnectionDatabase:
    def __init__(self):
        self.log      = Logger(name='connection')
        self.host     = os.getenv("DB_HOST")
        self.password = os.getenv("PASSWORD_SUPABASE")
        self.user     = os.getenv("DB_USER", "postgres")
        self.dbname   = os.getenv("DB_NAME", "postgres")
        self.port     = os.getenv("DB_PORT", "5432")

    def get_connection(self):
        if not self.host or not self.password:
            raise ValueError("DB_HOST ou PASSWORD_SUPABASE não encontrados no .env")
        return psycopg2.connect(
            dbname=self.dbname,
            user=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            connect_timeout=10
        )

    def execute_query(self, sql, params=None):
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return cur.fetchall()
        except Exception as e:
            self.log.error(f"Erro na query: {e}")
            return []
        finally:
            conn.close()

    def execute_command_returning(self, sql, params=None):
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                conn.commit()
                return rows
        except Exception as e:
            conn.rollback()
            self.log.error(f"Erro no comando com retorno: {e}")
            return []
        finally:
            conn.close()

    def execute_command(self, sql, params=None):
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                conn.commit()
                return True
        except Exception as e:
            conn.rollback()
            self.log.error(f"Erro no comando: {e}")
            return False
        finally:
            conn.close()
