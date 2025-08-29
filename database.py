# -*- coding: utf-8 -*-
import os
import mysql.connector
from mysql.connector import pooling
from dotenv import load_dotenv

# Carga las variables de entorno desde el archivo .env
# (DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, DB_PORT)
load_dotenv()

class DatabaseManager:
    """
    Gestiona toda la interacción con la base de datos MariaDB/MySQL.
    Utiliza un pool de conexiones para un rendimiento eficiente en un entorno de servidor web.
    """
    def __init__(self):
        """
        Inicializa el pool de conexiones a la base de datos y crea las tablas si no existen.
        """
        try:
            self.pool = mysql.connector.pooling.MySQLConnectionPool(
                pool_name="marketing_pool",
                pool_size=5, # Número de conexiones a mantener abiertas. 5 es un buen punto de partida.
                host=os.getenv("DB_HOST", "localhost"),
                user=os.getenv("DB_USER"),
                password=os.getenv("DB_PASSWORD"),
                database=os.getenv("DB_NAME"),
                port=os.getenv("DB_PORT", 3306)
            )
            print("✅ Pool de conexiones a MariaDB creado exitosamente.")
            self.setup_tables()
        except mysql.connector.Error as err:
            print(f"❌ Error crítico al conectar con MariaDB: {err}")
            # Si no se puede conectar a la BD, la aplicación no puede funcionar.
            exit(1)

    def execute_query(self, query, params=(), commit=False):
        """
        Ejecuta una consulta que no devuelve filas (INSERT, UPDATE, DELETE).
        Args:
            query (str): La consulta SQL con placeholders (%s).
            params (tuple): Los parámetros para la consulta.
            commit (bool): Si es True, confirma la transacción.
        Returns:
            Cursor: El cursor de la base de datos después de la ejecución.
        """
        # Obtiene una conexión del pool.
        conn = self.pool.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            if commit:
                conn.commit()
            return cursor
        except mysql.connector.Error as err:
            print(f"❌ Error de base de datos: {err}")
            conn.rollback() # Revierte los cambios en caso de error.
            return None
        finally:
            cursor.close()
            conn.close() # Devuelve la conexión al pool.

    def fetch_all(self, query, params=()):
        """
        Ejecuta una consulta y devuelve todas las filas encontradas como una lista de diccionarios.
        """
        conn = self.pool.get_connection()
        # dictionary=True es muy útil para devolver filas como {'columna': 'valor'}
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(query, params)
            return cursor.fetchall()
        finally:
            cursor.close()
            conn.close()

    def fetch_one(self, query, params=()):
        """
        Ejecuta una consulta y devuelve la primera fila encontrada como un diccionario.
        """
        conn = self.pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(query, params)
            return cursor.fetchone()
        finally:
            cursor.close()
            conn.close()
            
    def setup_tables(self):
        """
        Define y crea todo el esquema de la base de datos para el sistema multi-inquilino.
        Se ejecuta una sola vez al iniciar la aplicación.
        """
        # Se usa `ENGINE=InnoDB` porque es necesario para soportar claves foráneas.
        # `ON DELETE CASCADE` es la clave para la gestión de clientes: si un cliente se elimina,
        # todos sus datos asociados (textos, imágenes, etc.) se eliminan automáticamente.
        
        # 1. Tabla de Clientes: El núcleo del sistema multi-inquilino.
        create_clients_table = """
        CREATE TABLE IF NOT EXISTS clients (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            plan VARCHAR(50) NOT NULL DEFAULT 'free',
            trial_expires_at DATETIME NULL,
            publications_this_month INT NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
        """

        # 2. Tablas de Contenido: Cada registro pertenece a un cliente.
        create_texts_table = """
        CREATE TABLE IF NOT EXISTS texts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            client_id INT NOT NULL,
            content TEXT NOT NULL,
            ai_tags TEXT,
            usage_count INT DEFAULT 0,
            FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
        ) ENGINE=InnoDB;
        """
        
        create_images_table = """
        CREATE TABLE IF NOT EXISTS images (
            id INT AUTO_INCREMENT PRIMARY KEY,
            client_id INT NOT NULL,
            path VARCHAR(512) NOT NULL,
            manual_tags TEXT,
            UNIQUE KEY (client_id, path(255)),
            FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
        ) ENGINE=InnoDB;
        """

        # 3. Tablas de Destinos: También pertenecen a un cliente.
        create_groups_table = """
        CREATE TABLE IF NOT EXISTS groups (
            id INT AUTO_INCREMENT PRIMARY KEY,
            client_id INT NOT NULL,
            url VARCHAR(512) NOT NULL,
            tags TEXT,
            UNIQUE KEY (client_id, url(255)),
            FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
        ) ENGINE=InnoDB;
        """
        
        create_pages_table = """
        CREATE TABLE IF NOT EXISTS pages (
            id INT AUTO_INCREMENT PRIMARY KEY,
            client_id INT NOT NULL,
            name VARCHAR(255) NOT NULL,
            page_url VARCHAR(512) NOT NULL,
            UNIQUE KEY (client_id, page_url(255)),
            FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
        ) ENGINE=InnoDB;
        """
        
        # 4. Tablas de Operaciones y Logs
        create_scheduled_posts_table = """
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            client_id INT NOT NULL,
            page_id INT,
            publish_at DATETIME NOT NULL,
            text_content TEXT,
            image_id INT,
            status VARCHAR(50) DEFAULT 'pending',
            FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
        ) ENGINE=InnoDB;
        """

        create_publication_log_table = """
        CREATE TABLE IF NOT EXISTS publication_log (
            id INT AUTO_INCREMENT PRIMARY KEY,
            client_id INT NOT NULL,
            timestamp DATETIME NOT NULL,
            status VARCHAR(50) NOT NULL,
            target_type VARCHAR(50) NOT NULL,
            target_url VARCHAR(512),
            text_content TEXT,
            image_path VARCHAR(512),
            published_post_url VARCHAR(512),
            error_details TEXT,
            FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
        ) ENGINE=InnoDB;
        """

        # Lista de todos los comandos de creación de tablas
        commands = [
            create_clients_table,
            create_texts_table,
            create_images_table,
            create_groups_table,
            create_pages_table,
            create_scheduled_posts_table,
            create_publication_log_table
        ]
        
        print("🔧 Verificando y creando el esquema de la base de datos...")
        for command in commands:
            self.execute_query(command, commit=True)
        print("✅ Esquema de la base de datos listo.")

# --- Instancia Global ---
# Se crea una única instancia del gestor para que toda la aplicación la reutilice.
db_manager = DatabaseManager()

