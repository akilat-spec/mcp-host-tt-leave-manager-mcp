import os
import mysql.connector
from mysql.connector import Error
import logging

logger = logging.getLogger(__name__)

class DatabaseConnection:
    """MySQL database connection manager"""
    
    @staticmethod
    def get_connection():
        """
        Create and return a database connection
        """
        try:
            connection = mysql.connector.connect(
                host=os.environ.get("DB_HOST", "103.174.10.72"),
                user=os.environ.get("DB_USER", "tt_crm_mcp"),
                password=os.environ.get("DB_PASSWORD", "F*PAtqhu@sg2w58n"),
                database=os.environ.get("DB_NAME", "tt_crm_mcp"),
                port=int(os.environ.get("DB_PORT", "3306")),
                autocommit=True,
                connection_timeout=30,
                pool_size=5
            )
            
            if connection.is_connected():
                logger.debug("Database connection established successfully")
                return connection
                
        except Error as e:
            logger.error(f"Error connecting to MySQL database: {e}")
            raise
        
        except Exception as e:
            logger.error(f"Unexpected error connecting to database: {e}")
            raise
    
    @staticmethod
    def test_connection():
        """
        Test database connection
        """
        try:
            conn = DatabaseConnection.get_connection()
            if conn and conn.is_connected():
                conn.close()
                return True
            return False
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return False