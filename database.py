# -*- coding: utf-8 -*-
import sqlite3
from datetime import datetime

class DatabaseManager:
    def __init__(self, db_path="marketing_tool.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row # Permite acceder a las columnas por nombre
        self.setup_tables()

    def setup_tables(self):
        cursor = self.conn.cursor()
        
        # --- TABLAS DE CONTENIDO ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS texts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                ai_tags TEXT,
                usage_count INTEGER DEFAULT 0
            );
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                manual_tags TEXT
            );
        """)

        # --- TABLAS DE DESTINO ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                tags TEXT
            );
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                page_url TEXT NOT NULL UNIQUE
            );
        """)
        
        # --- TABLAS DE REGISTRO DE USO ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS group_image_usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id INTEGER,
                group_id INTEGER,
                timestamp DATETIME,
                FOREIGN KEY(image_id) REFERENCES images(id),
                FOREIGN KEY(group_id) REFERENCES groups(id)
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS group_text_usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text_id INTEGER,
                group_id INTEGER,
                timestamp DATETIME,
                FOREIGN KEY(text_id) REFERENCES texts(id),
                FOREIGN KEY(group_id) REFERENCES groups(id)
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS page_image_usage (
                page_id INTEGER,
                image_id INTEGER,
                PRIMARY KEY (page_id, image_id),
                FOREIGN KEY(page_id) REFERENCES pages(id),
                FOREIGN KEY(image_id) REFERENCES images(id)
            );
        """)

        # --- TABLAS DE OPERACIONES ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page_id INTEGER,
                publish_at DATETIME NOT NULL,
                text_content TEXT,
                image_id INTEGER,
                status TEXT DEFAULT 'pending', /* pending, processing, completed, failed */
                FOREIGN KEY(page_id) REFERENCES pages(id),
                FOREIGN KEY(image_id) REFERENCES images(id)
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS publication_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                status TEXT NOT NULL, /* Success, Failed */
                target_type TEXT NOT NULL, /* group, page */
                target_url TEXT,
                text_content TEXT,
                image_path TEXT,
                published_post_url TEXT
            );
        """)

        # --- MIGRACIÓN: Añadir columna usage_count a texts si no existe ---
        try:
            # Intenta seleccionar la columna para ver si existe.
            cursor.execute("SELECT usage_count FROM texts LIMIT 1")
        except sqlite3.OperationalError:
            # Si no existe, la añade.
            print("Realizando migración: Añadiendo 'usage_count' a la tabla 'texts'...") # <-- LÍNEA MODIFICADA
            cursor.execute("ALTER TABLE texts ADD COLUMN usage_count INTEGER DEFAULT 0")

        # --- MIGRACIÓN: Añadir columna error_details a publication_log si no existe ---
        try:
            # Intenta seleccionar la columna para ver si existe.
            cursor.execute("SELECT error_details FROM publication_log LIMIT 1")
        except sqlite3.OperationalError:
            # Si no existe, la añade.
            print("Realizando migración: Añadiendo 'error_details' a la tabla 'publication_log'...")
            cursor.execute("ALTER TABLE publication_log ADD COLUMN error_details TEXT")

        self.conn.commit()
        
    # --- MÉTODOS PARA OBTENER DATOS ---
    def get_all_data(self):
        cursor = self.conn.cursor()
        
        texts = [dict(row) for row in cursor.execute("SELECT * FROM texts ORDER BY id DESC").fetchall()]
        images = [dict(row) for row in cursor.execute("SELECT * FROM images ORDER BY id DESC").fetchall()]
        groups = [dict(row) for row in cursor.execute("SELECT * FROM groups ORDER BY id DESC").fetchall()]
        pages = [dict(row) for row in cursor.execute("SELECT * FROM pages ORDER BY id DESC").fetchall()]
        
        # Obtener scheduled posts con el nombre de la página
        scheduled_posts = [dict(row) for row in cursor.execute("""
            SELECT sp.*, p.name as page_name, i.path as image_path
            FROM scheduled_posts sp
            JOIN pages p ON sp.page_id = p.id
            LEFT JOIN images i ON sp.image_id = i.id
            ORDER BY sp.publish_at ASC
        """).fetchall()]

        return {
            "texts": texts,
            "images": images,
            "groups": groups,
            "pages": pages,
            "scheduled_posts": scheduled_posts
        }

    # --- MÉTODOS PARA ELIMINAR DATOS ---
    def delete_item(self, table, item_id):
        try:
            cursor = self.conn.cursor()
            cursor.execute(f"DELETE FROM {table} WHERE id = ?", (item_id,))
            self.conn.commit()
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # --- Métodos específicos para la lógica de la aplicación ---
    
    # ... (Se añadirán más métodos según los necesite AppLogic) ...

    def execute_query(self, query, params=()):
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        self.conn.commit()
        return cursor

    def fetch_all(self, query, params=()):
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def fetch_one(self, query, params=()):
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        row = cursor.fetchone()
        return dict(row) if row else None

# Instancia global para ser usada por toda la aplicación
db_manager = DatabaseManager()