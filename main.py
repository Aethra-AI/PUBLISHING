# -*- coding: utf-8 -*-
import os
import random
import time
import threading
import uuid
import shutil
from datetime import datetime, timedelta, date
from queue import Queue
from functools import wraps

# --- Módulos del Proyecto ---
# Asegúrate de tener tu nuevo database.py para MariaDB y ai_services.py
from database import db_manager
from ai_services import ai_service

# --- Utilidades y Seguridad ---
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# --- Framework Web y Autenticación ---
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, join_room, disconnect
from flask_jwt_extended import create_access_token, get_jwt, jwt_required, JWTManager, decode_token

# --- Lógica de Automatización (Selenium) ---
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import WebDriverException, TimeoutException

# --- Carga de variables de entorno ---
from dotenv import load_dotenv
load_dotenv()

# ==============================================================================
# --- CONFIGURACIÓN DE LA APLICACIÓN ---
# ==============================================================================

app = Flask(__name__)
CORS(app) # Permite peticiones desde tu frontend en Github Pages

# --- Configuración de Seguridad y JWT ---
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "una-clave-muy-secreta-y-dificil-de-adivinar")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=24)
SUPERUSER_API_KEY = os.getenv("SUPERUSER_API_KEY")
if not SUPERUSER_API_KEY:
    raise ValueError("SUPERUSER_API_KEY no está definida en el archivo .env")
jwt = JWTManager(app)
# Esta función se ejecuta cada vez que se accede a una ruta protegida.
# Carga el usuario desde la BD basado en la identidad del token.
# Si el usuario no existe (ej. fue eliminado), el token se considera inválido.



@jwt.user_lookup_loader
def user_lookup_callback(_jwt_header, jwt_data):
    """
    Esta función se llama en cada petición protegida.
    'sub' contiene la identidad (el client_id) del token.
    Devuelve el objeto de usuario si se encuentra en la BD, o None si no.
    """
    identity = jwt_data.get("sub")
    if not identity:
        return None
    try:
        identity = int(identity)
    except (TypeError, ValueError):
        return None
    return db_manager.fetch_one("SELECT * FROM clients WHERE id = %s", (identity,))

# --- Configuración de Archivos y Workers ---
app.config['UPLOAD_FOLDER'] = os.path.abspath('client_uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
# Límite de navegadores simultáneos para una VM de 4GB. Ajustable.
MAX_CONCURRENT_BROWSERS = 3
job_queue = Queue()

# --- Planes de Suscripción (Configuración Central) ---
PLANS = {
    'free': {'limit': 50, 'price': 0, 'name': 'Prueba Gratuita'},
    'basic': {'limit': 500, 'price': 10, 'name': 'Plan Básico'},
    'pro': {'limit': 1000, 'price': 15, 'name': 'Plan Profesional'},
    'unlimited': {'limit': float('inf'), 'price': 50, 'name': 'Plan Ilimitado'}
}

# --- WebSockets para Logs en Tiempo Real ---
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')


# ==============================================================================
# --- LÓGICA DE AUTOMATIZACIÓN Y GESTIÓN DE INSTANCIAS ---
# ==============================================================================

class AppLogic:
    """Contiene toda la lógica de automatización para UN SOLO cliente."""
    def __init__(self, client_id, socket_io_instance):
        self.client_id = client_id
        self.socketio = socket_io_instance
        self.driver = None
        self.is_publishing = False
        self.profile_path = os.path.abspath(f'profiles/client_{self.client_id}')
        os.makedirs(self.profile_path, exist_ok=True)

    def log_to_panel(self, message, log_type='info'):
        """Envía un mensaje de log al frontend a través de WebSockets a la sala del cliente."""
        timestamp = time.strftime('%H:%M:%S')
        formatted_message = f"[{timestamp}] {message}"
        self.socketio.emit('log_message', {'data': formatted_message, 'type': log_type}, room=self.client_id)
        print(f"[Cliente {self.client_id}] {formatted_message}")

    def get_chrome_options(self, headless=True):
        """Genera las opciones de Chrome, permitiendo modo no-headless para login."""
        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument(f"user-data-dir={self.profile_path}")
        return options

    def init_browser(self, headless=True):
        """Inicia una instancia de navegador para este cliente."""
        try:
            self.log_to_panel("Configurando instancia de Chrome...")
            service = ChromeService(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=self.get_chrome_options(headless=headless))
            self.log_to_panel("Navegador iniciado y listo.")
            return True
        except Exception as e:
            self.log_to_panel(f"Error crítico al iniciar Chrome: {e}", "error")
            return False

    def close_browser(self):
        """Cierra la instancia del navegador si está abierta."""
        if self.driver:
            try:
                self.driver.quit()
            finally:
                self.driver = None
                self.log_to_panel("Instancia del navegador cerrada.")
    
    # --- LÓGICA DE SELENIUM PORTADA DEL SCRIPT ORIGINAL ---
    # Se mantienen los XPaths y la robusta lógica de reintentos.

    def _validate_image_path(self, image_path):
        """Valida que un archivo de imagen exista y sea accesible."""
        if not image_path: return {"valid": True, "path": None, "error": None}
        try:
            abs_path = os.path.abspath(image_path)
            if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
                error = "Archivo no encontrado o no es un archivo"
                self.log_to_panel(f"⚠️ Imagen inválida: {os.path.basename(image_path)} ({error})", "warning")
                return {"valid": False, "path": abs_path, "error": error}
            return {"valid": True, "path": abs_path, "error": None}
        except Exception as e:
            self.log_to_panel(f"⚠️ Error validando imagen: {e}", "warning")
            return {"valid": False, "path": image_path, "error": str(e)}

    def _create_post_on_facebook(self, text_content, image_path=None, max_retries=3):
        """
        Crea una publicación en Facebook. MANTIENE LOS XPATH ORIGINALES para máxima compatibilidad.
        """
        image_validation = self._validate_image_path(image_path)
        if not image_validation["valid"]:
            self.log_to_panel(f"IMAGEN INVÁLIDA: {image_validation['error']}. Publicando solo texto.", "warning")
            image_path = None
        else:
            image_path = image_validation["path"]
        
        for attempt in range(max_retries):
            try:
                # 1. Abrir el modal de publicación con varios selectores de respaldo
                self.log_to_panel(f"Intento {attempt + 1}: Abriendo cuadro de publicación...")
                open_button_selectors = [
                    '//div[contains(@aria-label, "Crear una publicación")]',
                    '//*[contains(text(), "Escribe algo")]',
                    '//div[contains(@role, "button") and contains(text(), "Escribe algo")]',
                    '//div[contains(@aria-label, "¿En qué estás pensando")]'
                ]
                open_button = None
                for selector in open_button_selectors:
                    try:
                        open_button = WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((By.XPATH, selector)))
                        if open_button: break
                    except TimeoutException: continue
                
                if not open_button: raise Exception("No se encontró el botón/cuadro para crear una publicación.")
                open_button.click()
                time.sleep(random.uniform(2, 4))

                # 2. Escribir el texto de forma humanizada
                self.log_to_panel("Escribiendo contenido...")
                post_box = self.driver.switch_to.active_element
                for char in text_content:
                    post_box.send_keys(char)
                    time.sleep(random.uniform(0.05, 0.1))
                
                # 3. Subir imagen si existe
                if image_path:
                    self.log_to_panel(f"Subiendo imagen: {os.path.basename(image_path)}")
                    # Facebook oculta el input, por lo que es necesario encontrarlo sin importar su visibilidad
                    file_input = self.driver.find_element(By.XPATH, "//input[@type='file']")
                    file_input.send_keys(image_path)
                    # Esperar a que la miniatura de la imagen aparezca como confirmación de subida
                    WebDriverWait(self.driver, 45).until(EC.presence_of_element_located((By.XPATH, "//div[contains(@aria-label, 'foto')] | //img[contains(@src, 'blob:')]")))
                    self.log_to_panel("Imagen subida correctamente.")

                # 4. Publicar
                self.log_to_panel("Buscando botón de Publicar...")
                publish_button = WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//div[@aria-label='Publicar' and @role='button']")))
                publish_button.click()
                self.log_to_panel("Publicación enviada.")
                
                # 5. Intentar obtener la URL de la publicación para el log
                post_url = None
                try:
                    view_post_button = WebDriverWait(self.driver, 15).until(EC.element_to_be_clickable((By.XPATH, "//a[.//span[contains(text(), 'Ver publicación')]]")))
                    post_url = view_post_button.get_attribute('href')
                    self.log_to_panel(f"URL de publicación obtenida: {post_url}")
                except TimeoutException:
                    self.log_to_panel("No se pudo obtener la URL de la publicación, pero el proceso probablemente fue exitoso.", "warning")

                return {"success": True, "post_url": post_url}

            except Exception as e:
                self.log_to_panel(f"Error en intento de publicación {attempt + 1}/{max_retries}: {e}", "error")
                if attempt == max_retries - 1:
                    return {"success": False, "error": str(e)}
                time.sleep(5) # Esperar antes de reintentar
        return {"success": False, "error": "Fallaron todos los reintentos de publicación."}
    

    def _find_coherent_pair_for_group(self, content_tags_str):
        """
        Encuentra un par de texto e imagen coherentes y menos usados para este cliente,
        basado en una lista de etiquetas de contenido.
        """
        # 1. Limpiar y validar las etiquetas de entrada
        content_tags = [tag.strip() for tag in content_tags_str.split(',') if tag.strip()]
        if not content_tags:
            self.log_to_panel("No se proporcionaron etiquetas de contenido válidas para la búsqueda.", "warning")
            return None, None

        self.log_to_panel(f"Buscando contenido con etiquetas: {', '.join(content_tags)}...")

        # 2. Construir dinámicamente la parte de la query SQL para las etiquetas
        #    Esto previene inyección SQL ya que los valores se pasan como parámetros.
        #    Ejemplo: "ai_tags LIKE %s OR ai_tags LIKE %s"
        tags_query_part = " OR ".join(["ai_tags LIKE %s" for _ in content_tags])
    
        # 3. Preparar los parámetros para la query. El formato %tag% busca la etiqueta en cualquier parte del string.
        #    Ejemplo: ('%coche%', '%venta%')
        params_like = tuple([f"%{tag}%" for tag in content_tags])
     
        # 4. Construir y ejecutar la query para encontrar el texto menos usado que coincida
        text_query = f"""
            SELECT * FROM texts 
            WHERE client_id = %s AND ({tags_query_part})
            ORDER BY usage_count ASC, RAND() 
            LIMIT 1
        """
        text_params = (self.client_id,) + params_like
        text = db_manager.fetch_one(text_query, text_params)

        if not text:
            self.log_to_panel("No se encontraron textos que coincidan con las etiquetas.", "warning")
            return None, None

        # 5. Ahora, buscar una imagen coherente usando las etiquetas del texto encontrado.
        #    Esto asegura una mayor coherencia. Usamos las etiquetas IA del texto.
        image_tags_str = text.get('ai_tags', '')
        image_tags = [tag.strip() for tag in image_tags_str.split(',') if tag.strip()]
    
        if not image_tags:
            self.log_to_panel(f"El texto ID {text['id']} no tiene etiquetas IA para buscar una imagen. Buscando imagen aleatoria.", "warning")
            # Plan B: Si el texto no tiene etiquetas, busca una imagen aleatoria.
            image = db_manager.fetch_one("SELECT * FROM images WHERE client_id = %s ORDER BY RAND() LIMIT 1", (self.client_id,))
        else:
            image_tags_query_part = " OR ".join(["manual_tags LIKE %s" for _ in image_tags])
            image_params_like = tuple([f"%{tag}%" for tag in image_tags])
        
            image_query = f"""
                SELECT * FROM images 
                WHERE client_id = %s AND ({image_tags_query_part})
                ORDER BY RAND() 
                LIMIT 1
            """
            image_params = (self.client_id,) + image_params_like
            image = db_manager.fetch_one(image_query, image_params)

        if not image:
            self.log_to_panel("No se encontró una imagen coherente. Buscando cualquier imagen disponible como último recurso.", "warning")
            # Plan C: Si no hay imagen coherente, busca CUALQUIER imagen del cliente.
            image = db_manager.fetch_one("SELECT * FROM images WHERE client_id = %s ORDER BY RAND() LIMIT 1", (self.client_id,))

        if text and image:
            self.log_to_panel(f"Par de contenido encontrado: Texto ID {text['id']}, Imagen ID {image['id']}", "info")
            return text, image
    
        self.log_to_panel("Fallo al encontrar un par de contenido válido (Texto o Imagen no disponibles).", "error")
        return None, None

    def _group_publishing_process(self, group_tags, content_tags):
        """
        Proceso completo de publicación en grupos para este cliente.
        """
        self.is_publishing = True
        if not self.init_browser():
            self.is_publishing = False
            self.socketio.emit('publishing_status', {'isPublishing': False}, room=self.client_id)
            return

        try:
            # Consulta adaptada para multi-inquilino y sintaxis de MariaDB/MySQL
            query_tags = [f"tags LIKE %s" for tag in group_tags.split(',')]
            query = f"SELECT * FROM groups WHERE client_id = %s AND ({' OR '.join(query_tags)})"
            params = (self.client_id,) + tuple([f"%{tag.strip()}%" for tag in group_tags.split(',')])
            groups_to_publish = db_manager.fetch_all(query, params)
            
            self.log_to_panel(f"Publicación iniciada. {len(groups_to_publish)} grupos encontrados para las etiquetas seleccionadas.")
            
            for i, group in enumerate(groups_to_publish):
                if not self.is_publishing:
                    self.log_to_panel("Proceso detenido por el usuario.", "warning")
                    break
                
                self.log_to_panel(f"--- ({i+1}/{len(groups_to_publish)}) Procesando grupo: {group['url']} ---")
                text, image = self._find_coherent_pair_for_group(content_tags)
                
                if not text or not image:
                    self.log_to_panel("No se encontró un par de contenido coherente y disponible. Saltando grupo.", "warning")
                    time.sleep(random.uniform(5, 10))
                    continue

                try:
                    self.driver.get(group['url'])
                    time.sleep(random.uniform(5, 8))
                    
                    result = self._create_post_on_facebook(text['content'], image['path'])
                    
                    # Registrar en el log de publicaciones
                    db_manager.execute_query(
                        """INSERT INTO publication_log (client_id, timestamp, status, target_type, target_url, text_content, image_path, published_post_url, error_details)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (self.client_id, datetime.utcnow(), 'Success' if result['success'] else 'Failed', 'group', group['url'], text['content'], image['path'], result.get('post_url'), None if result['success'] else result.get('error')),
                        commit=True
                    )

                    if result['success']:
                        self.log_to_panel(f"✅ Publicación exitosa en {group['url']}", 'success')
                        # Incrementar contadores de uso
                        db_manager.execute_query("UPDATE texts SET usage_count = usage_count + 1 WHERE id = %s AND client_id = %s", (text['id'], self.client_id), commit=True)
                        # Incrementar contador de publicaciones del mes si fue exitosa
                        db_manager.execute_query(
                            "UPDATE clients SET publications_this_month = publications_this_month + 1 WHERE id = %s",
                            (self.client_id,), commit=True
                        )
                    else:
                        self.log_to_panel(f"❌ Falló la publicación en {group['url']}: {result.get('error')}", "error")

                except Exception as e:
                    self.log_to_panel(f"❌ Error inesperado procesando el grupo {group['url']}: {e}", "error")

                # Pausa entre publicaciones
                wait_time = random.randint(60, 120)
                self.log_to_panel(f"Esperando {wait_time} segundos antes del siguiente grupo...")
                time.sleep(wait_time)

        finally:
            self.close_browser()
            self.is_publishing = False
            self.log_to_panel("Proceso de publicación finalizado.")
            self.socketio.emit('publishing_status', {'isPublishing': False}, room=self.client_id)



class InstanceManager:
    """Gestiona una instancia de AppLogic para cada cliente, evitando crear duplicados."""
    def __init__(self):
        self.instances = {}
        self.lock = threading.Lock()

    def get_logic(self, client_id):
        with self.lock:
            if client_id not in self.instances:
                self.instances[client_id] = AppLogic(client_id, socketio)
            return self.instances[client_id]

# La instanciación ocurre AQUÍ, después de que la clase ha sido definida.
instance_manager = InstanceManager()


def admin_required(fn):
    """Decorador para proteger rutas de admin, requiere una clave de API en la cabecera."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth_key = request.headers.get('X-Admin-API-Key')
        if auth_key and auth_key == SUPERUSER_API_KEY:
            return fn(*args, **kwargs)
        else:
            return jsonify({"msg": "Acceso de administrador requerido"}), 403
    return wrapper


def check_subscription_limit(fn):
    """
    Decorador que se aplica a rutas protegidas para verificar el límite del plan.
    IMPORTANTE: Debe aplicarse DESPUÉS de @jwt_required().
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        # Obtenemos el ID del cliente directamente del token JWT.
        client_id = get_jwt()['sub']

        # Buscamos la información del plan del cliente en la base de datos.
        client = db_manager.fetch_one(
            "SELECT plan, trial_expires_at, publications_this_month FROM clients WHERE id = %s", 
            (client_id,)
        )
        
        # Si por alguna razón el cliente no existe, denegar acceso.
        if not client:
            return jsonify({"msg": "Cliente no encontrado para el token proporcionado."}), 404

        # Verificar si el período de prueba ha expirado para el plan 'free'.
        trial_expires_at = client.get('trial_expires_at')
        if client['plan'] == 'free' and trial_expires_at and datetime.utcnow() > trial_expires_at:
            return jsonify({"msg": "Tu período de prueba ha expirado. Por favor, actualiza tu plan."}), 403

        # Obtener el límite de publicaciones del plan actual.
        plan_limit = PLANS.get(client['plan'], {'limit': 0}).get('limit', 0)
        
        # Comparar el uso actual con el límite del plan.
        if client['publications_this_month'] >= plan_limit:
            return jsonify({
                "msg": f"Has alcanzado el límite de {plan_limit} publicaciones de tu plan para este mes."
            }), 403
            
        # Si todas las verificaciones pasan, ejecutar la función original de la ruta.
        return fn(*args, **kwargs)
    return wrapper
# ==============================================================================
# --- WORKER E INSTANCIAS ---
# ==============================================================================
instance_manager = InstanceManager()

def job_worker():
    """Procesa trabajos de la cola de forma secuencial para no sobrecargar la VM."""
    while True:
        job = job_queue.get()
        client_id = job.get('client_id')
        task_type = job.get('task_type')
        data = job.get('data')
        logic_instance = instance_manager.get_logic(client_id)
        
        if task_type == 'publish_to_groups':
            logic_instance._group_publishing_process(data['group_tags'], data['content_tags'])
        # Aquí se podrían añadir otros tipos de trabajos pesados en el futuro
        
        job_queue.task_done()

# ==============================================================================
# --- API ENDPOINTS COMPLETOS ---
# ==============================================================================

# --- Autenticación y Gestión de Cuentas ---

@app.route('/api/auth/login', methods=['POST'])
def login():
    email = request.json.get("email", None)
    password = request.json.get("password", None)
    
    client = db_manager.fetch_one("SELECT * FROM clients WHERE email = %s", (email,))
    
    if client and check_password_hash(client['password_hash'], password):
        # La identidad del token (sub) debe ser STRING para cumplir con JWT (RFC 7519)
        access_token = create_access_token(identity=str(client['id']))
        return jsonify(access_token=access_token, clientName=client['name'], clientId=client['id'])
    
    return jsonify({"msg": "Email o contraseña incorrectos"}), 401

@app.route('/api/account/change-password', methods=['PUT'])
@jwt_required()
def change_password():
    client_id = get_jwt()['sub']
    current_password = request.json.get("current_password")
    new_password = request.json.get("new_password")

    client = db_manager.fetch_one("SELECT password_hash FROM clients WHERE id = %s", (client_id,))
    if not client or not check_password_hash(client['password_hash'], current_password):
        return jsonify({"msg": "La contraseña actual es incorrecta"}), 401
    
    new_password_hash = generate_password_hash(new_password)
    db_manager.execute_query("UPDATE clients SET password_hash = %s WHERE id = %s", (new_password_hash, client_id), commit=True)
    return jsonify({"msg": "Contraseña actualizada correctamente."})

@app.route('/api/account/status', methods=['GET'])
@jwt_required()
def get_account_status():
    client_id = get_jwt()['sub']
    client = db_manager.fetch_one("SELECT name, email, plan, trial_expires_at, created_at, publications_this_month FROM clients WHERE id = %s", (client_id,))
    
    plan_info = PLANS.get(client['plan'], {})
    client_status = {
        "name": client['name'],
        "email": client['email'],
        "plan": client['plan'],
        "trial_expires_at": client['trial_expires_at'].isoformat() if client.get('trial_expires_at') else None,
        "created_at": client['created_at'].isoformat() if client.get('created_at') else None,
        "plan_name": plan_info.get('name'),
        "monthly_limit": plan_info.get('limit'),
        "monthly_usage": client['publications_this_month']
    }
    return jsonify(client_status)
# --- Endpoints de Superusuario ---
@app.route('/api/admin/clients', methods=['POST'])
@admin_required
def create_client():
    """Crea una nueva cuenta de cliente."""
    data = request.get_json()
    name = data.get("name")
    email = data.get("email")
    password = data.get("password")
    plan = data.get("plan", "free")
    trial_days = data.get("trial_days", 3)

    if not all([name, email, password]): return jsonify({"msg": "Faltan datos: nombre, email y contraseña son requeridos"}), 400
    if plan not in PLANS: return jsonify({"msg": f"Plan '{plan}' no es válido. Opciones: {list(PLANS.keys())}"}), 400
    if db_manager.fetch_one("SELECT id FROM clients WHERE email = %s", (email,)): return jsonify({"msg": f"El email '{email}' ya está en uso"}), 409
        
    password_hash = generate_password_hash(password)
    trial_expires_at = datetime.utcnow() + timedelta(days=trial_days) if plan == 'free' else None
    
    db_manager.execute_query(
        "INSERT INTO clients (name, email, password_hash, plan, trial_expires_at) VALUES (%s, %s, %s, %s, %s)",
        (name, email, password_hash, plan, trial_expires_at), commit=True
    )
    return jsonify({"msg": f"Cliente '{name}' creado con plan '{plan}'."})

@app.route('/api/admin/clients/<int:client_id>', methods=['DELETE'])
@admin_required
def delete_client(client_id):
    """Elimina una cuenta de cliente y todos sus datos asociados."""
    # El `ON DELETE CASCADE` en la base de datos se encargará de borrar los datos en otras tablas.
    cursor = db_manager.execute_query("DELETE FROM clients WHERE id = %s", (client_id,), commit=True)
    if cursor.rowcount == 0:
        return jsonify({"msg": "Cliente no encontrado"}), 404
    
    # Eliminar sus archivos y perfil de Chrome del servidor
    shutil.rmtree(f'client_uploads/client_{client_id}', ignore_errors=True)
    shutil.rmtree(f'profiles/client_{client_id}', ignore_errors=True)
    
    return jsonify({"msg": f"Cliente {client_id} y todos sus datos han sido eliminados."})

@app.route('/api/admin/clients/<int:client_id>/plan', methods=['PUT'])
@admin_required
def update_client_plan(client_id):
    """Actualiza el plan de suscripción de un cliente."""
    new_plan = request.json.get("plan")
    if new_plan not in PLANS:
        return jsonify({"msg": "Plan no válido"}), 400
        
    db_manager.execute_query(
        "UPDATE clients SET plan = %s, trial_expires_at = NULL WHERE id = %s", 
        (new_plan, client_id), commit=True
    )
    return jsonify({"msg": f"Cliente {client_id} actualizado al plan '{new_plan}'."})

# --- Endpoint para servir imágenes (con configuración Nginx recomendada) ---
@app.route('/uploads/client_<int:client_id>/<path:filename>')
def serve_uploaded_file(client_id, filename):
    """
    Sirve los archivos subidos por un cliente. 
    En producción, esto debe ser manejado por Nginx para mayor eficiencia.
    EJEMPLO DE CONFIGURACIÓN NGINX (en /etc/nginx/sites-available/your_site):
    location /uploads/ {
        # Sirve archivos estáticos directamente, mucho más rápido que Flask.
        alias /var/www/your_project/client_uploads/;
        expires 30d;
        add_header Cache-Control "public";
    }
    """
    directory = os.path.join(app.config['UPLOAD_FOLDER'], f'client_{client_id}')
    return send_from_directory(directory, filename)


# --- API de Datos y Funcionalidades (TODAS PORTADAS Y PROTEGIDAS) ---

# main.py

# =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=
# ====== BLOQUE COMPLETO PARA REEMPLAZAR (get_initial_data) ======
# =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

@app.route('/api/data/initial', methods=['GET'])
@jwt_required() 
def get_initial_data():
    """
    Recopila y devuelve todos los datos iniciales necesarios para que el cliente
    cargue su panel de control.
    """
    # 1. Obtiene el ID del cliente de forma segura desde el token JWT validado.
    client_id_raw = get_jwt().get('sub')
    try:
        client_id = int(client_id_raw)
    except (TypeError, ValueError):
        return jsonify({"msg": "Token inválido."}), 401
    
    # 2. Obtiene la información básica del cliente.
    client_info = db_manager.fetch_one("SELECT id, name FROM clients WHERE id=%s", (client_id,))
    
    # 3. Recopila todos los datos asociados a ese client_id.
    #    Las consultas están completas y ordenadas para una mejor visualización.
    data = {
        "client_info": client_info,
        "texts": db_manager.fetch_all(
            "SELECT * FROM texts WHERE client_id = %s ORDER BY id DESC", (client_id,)
        ),
        "images": db_manager.fetch_all(
            "SELECT * FROM images WHERE client_id = %s ORDER BY id DESC", (client_id,)
        ),
        "groups": db_manager.fetch_all(
            "SELECT * FROM groups WHERE client_id = %s ORDER BY id DESC", (client_id,)
        ),
        "pages": db_manager.fetch_all(
            "SELECT * FROM pages WHERE client_id = %s ORDER BY id DESC", (client_id,)
        ),
        "scheduled_posts": db_manager.fetch_all(
            "SELECT sp.*, p.name as page_name FROM scheduled_posts sp LEFT JOIN pages p ON sp.page_id = p.id WHERE sp.client_id = %s ORDER BY sp.publish_at DESC", (client_id,)
        ),
        "publication_log": db_manager.fetch_all(
            "SELECT * FROM publication_log WHERE client_id = %s ORDER BY timestamp DESC LIMIT 50", (client_id,)
        )
    }

    # 4. Devuelve el paquete completo de datos al frontend.
    return jsonify(data)

@app.route('/api/texts', methods=['POST'])
@jwt_required()
def add_text():
    client_id_raw = get_jwt().get('sub')
    try:
        client_id = int(client_id_raw)
    except (TypeError, ValueError):
        return jsonify({"msg": "Token inválido."}), 401
    content = request.json.get('content')
    if not content: return jsonify({"msg": "El contenido no puede estar vacío"}), 400
    
    try:
        tags = ai_service.generate_tags_for_text(content)
        tags_str = ",".join(tags) if tags else ""
    except Exception as e:
        print(f"ADVERTENCIA: Falló la generación de etiquetas por IA: {e}")
        tags_str = "" # Continuar sin etiquetas en caso de error de la IA

    


    db_manager.execute_query("INSERT INTO texts (client_id, content, ai_tags) VALUES (%s, %s, %s)", (client_id, content, tags_str), commit=True)
    new_texts = db_manager.fetch_all("SELECT * FROM texts WHERE client_id = %s ORDER BY id DESC", (client_id,))
    return jsonify(new_texts)

@app.route('/api/images/upload', methods=['POST'])
@jwt_required()
def upload_images():
    client_id_raw = get_jwt().get('sub')
    try:
        client_id = int(client_id_raw)
    except (TypeError, ValueError):
        return jsonify({"msg": "Token inválido."}), 401
    if 'images' not in request.files: return jsonify({"msg": "No se encontraron archivos"}), 400
        
    files = request.files.getlist('images')
    tags = request.form.get('tags', '')
    client_upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], f'client_{client_id}')
    os.makedirs(client_upload_dir, exist_ok=True)
    
    for file in files:
        filename = secure_filename(file.filename)
        unique_filename = f"{int(time.time())}_{filename}"
        save_path = os.path.join(client_upload_dir, unique_filename)
        file.save(save_path)
        # Guardamos solo el nombre del archivo, no la ruta completa, es más seguro y portable
        db_manager.execute_query("INSERT INTO images (client_id, path, manual_tags) VALUES (%s, %s, %s)", (client_id, unique_filename, tags), commit=True)
        
    new_images = db_manager.fetch_all("SELECT * FROM images WHERE client_id = %s ORDER BY id DESC", (client_id,))
    return jsonify(new_images)
@app.route('/api/texts/<int:item_id>', methods=['PUT'])
@jwt_required()
def update_text(item_id):
    client_id_raw = get_jwt().get('sub')
    try:
        client_id = int(client_id_raw)
    except (TypeError, ValueError):
        return jsonify({"msg": "Token inválido."}), 401
    content = request.json.get('content')
    text_obj = db_manager.fetch_one("SELECT id FROM texts WHERE id = %s AND client_id = %s", (item_id, client_id))
    if not text_obj: return jsonify({"msg": "Texto no encontrado o no autorizado"}), 404
    
    # tags = ai_service.generate_tags_for_text(content) # Descomenta si usas ai_service
    try:
        tags = ai_service.generate_tags_for_text(content)
        tags_str = ",".join(tags) if tags else ""
    except Exception as e:
        print(f"ADVERTENCIA: Falló la generación de etiquetas por IA al actualizar: {e}")
        tags_str = ""

    db_manager.execute_query("UPDATE texts SET content = %s, ai_tags = %s WHERE id = %s", (content, tags_str, item_id), commit=True)
    updated_texts = db_manager.fetch_all("SELECT * FROM texts WHERE client_id = %s ORDER BY id DESC", (client_id,))
    return jsonify(updated_texts)





@app.route('/api/texts/generate-ai', methods=['POST'])
@jwt_required()
def generate_ai_texts():
    client_id_raw = get_jwt().get('sub')
    try:
        client_id = int(client_id_raw)
    except (TypeError, ValueError):
        return jsonify({"msg": "Token inválido."}), 401
    
    data = request.get_json()
    topic = data.get('topic')
    count = data.get('count', 5)

    if not topic:
        return jsonify({"msg": "Se requiere un tema para la generación."}), 400

    try:
        print(f"INFO: [Cliente {client_id}] Iniciando generación de {count} textos sobre '{topic}'.")
        
        generated_texts = ai_service.generate_text_variations(topic, count)
        
        # Log para ver qué nos devuelve la IA
        print(f"INFO: [Cliente {client_id}] OpenAI devolvió {len(generated_texts)} textos.")
        # print(f"DEBUG: Textos recibidos: {generated_texts}") # Descomenta para ver el contenido exacto

        if not generated_texts:
            print(f"WARN: [Cliente {client_id}] OpenAI no devolvió textos. Terminando la operación sin cambios.")
            # Devolvemos la lista actual para que el frontend no se rompa
            current_texts = db_manager.fetch_all("SELECT * FROM texts WHERE client_id = %s ORDER BY id DESC", (client_id,))
            return jsonify(current_texts)
            
        print(f"INFO: [Cliente {client_id}] Guardando {len(generated_texts)} textos en la base de datos.")
        for text_content in generated_texts:
            try:
                tags = ai_service.generate_tags_for_text(text_content)
                tags_str = ",".join(tags) if tags else ""
            except Exception as e_tags:
                print(f"WARN: Falló la generación de etiquetas para un texto: {e_tags}")
                tags_str = ""
            
            db_manager.execute_query(
                "INSERT INTO texts (client_id, content, ai_tags) VALUES (%s, %s, %s)",
                (client_id, text_content, tags_str),
                commit=True
            )
        
        print(f"INFO: [Cliente {client_id}] Textos guardados exitosamente. Devolviendo lista actualizada.")
        new_texts = db_manager.fetch_all("SELECT * FROM texts WHERE client_id = %s ORDER BY id DESC", (client_id,))
        return jsonify(new_texts)

    except Exception as e:
        # Este log es crucial para ver si hay un error inesperado
        print(f"ERROR: Excepción CRÍTICA en generate_ai_texts: {e}")
        return jsonify({"msg": f"Error al generar textos: {str(e)}"}), 500
    

@app.route('/api/items/<table>/<int:item_id>', methods=['DELETE'])
@jwt_required()
def delete_item(table, item_id):
    client_id_raw = get_jwt().get('sub')
    try:
        client_id = int(client_id_raw)
    except (TypeError, ValueError):
        return jsonify({"msg": "Token inválido."}), 401
    allowed_tables = ['texts', 'images', 'groups', 'pages', 'scheduled_posts']
    if table not in allowed_tables:
        return jsonify({"msg": "Operación no permitida"}), 400

    if table == 'images':
        image_record = db_manager.fetch_one("SELECT path FROM images WHERE id = %s AND client_id = %s", (item_id, client_id))
        if image_record:
            # Construye la ruta completa para borrar el archivo
            full_path = os.path.join(app.config['UPLOAD_FOLDER'], f'client_{client_id}', image_record['path'])
            if os.path.exists(full_path):
                os.remove(full_path)

    query = f"DELETE FROM {table} WHERE id = %s AND client_id = %s"
    cursor = db_manager.execute_query(query, (item_id, client_id), commit=True)
    
    if cursor.rowcount == 0:
        return jsonify({"msg": "Elemento no encontrado o no autorizado"}), 404

    # Devuelve la lista actualizada del tipo de dato correspondiente
    updated_data = db_manager.fetch_all(f"SELECT * FROM {table} WHERE client_id = %s ORDER BY id DESC", (client_id,))
    return jsonify({"success": True, "msg": f"Elemento eliminado.", "updated_data": updated_data})


@app.route('/api/groups', methods=['POST'])
@jwt_required()
def add_group():
    client_id = get_jwt()['sub']
    data = request.get_json()
    db_manager.execute_query("INSERT INTO groups (client_id, url, tags) VALUES (%s, %s, %s)", (client_id, data['url'], data['tags']), commit=True)
    return jsonify(db_manager.fetch_all("SELECT * FROM groups WHERE client_id = %s ORDER BY id DESC", (client_id,)))

@app.route('/api/pages', methods=['POST'])
@jwt_required()
def add_page():
    client_id_raw = get_jwt().get('sub')
    try:
        client_id = int(client_id_raw)
    except (TypeError, ValueError):
        return jsonify({"msg": "Token inválido."}), 401
    data = request.get_json()
    db_manager.execute_query("INSERT INTO pages (client_id, name, page_url) VALUES (%s, %s, %s)", (client_id, data['name'], data['page_url']), commit=True)
    return jsonify(db_manager.fetch_all("SELECT * FROM pages WHERE client_id = %s ORDER BY id DESC", (client_id,)))

@app.route('/api/scheduled_posts', methods=['POST'])
@jwt_required()
def add_scheduled_post():
    client_id_raw = get_jwt().get('sub')
    try:
        client_id = int(client_id_raw)
    except (TypeError, ValueError):
        return jsonify({"msg": "Token inválido."}), 401
    data = request.get_json()
    db_manager.execute_query("INSERT INTO scheduled_posts (client_id, page_id, publish_at, text_content, image_id) VALUES (%s, %s, %s, %s, %s)", (client_id, data['page_id'], data['publish_at'], data['text_content'], data.get('image_id')), commit=True)
    return jsonify(db_manager.fetch_all("SELECT sp.*, p.name as page_name FROM scheduled_posts sp LEFT JOIN pages p ON sp.page_id = p.id WHERE sp.client_id = %s ORDER BY sp.publish_at DESC", (client_id,)))


# main.py


@app.route('/api/publishing/start', methods=['POST'])
@jwt_required()
@check_subscription_limit
def start_publishing():
    # Obtenemos el client_id del token.
    client_id_raw = get_jwt().get('sub')
    try:
        client_id = int(client_id_raw)
    except (TypeError, ValueError):
        return jsonify({"msg": "Token inválido."}), 401

    # --- LÍNEA CORREGIDA ---
    # En lugar de verificar si el cliente está en el gestor,
    # obtenemos directamente su instancia de lógica.
    # El método .get_logic() se encarga de crearla si no existe.
    logic = instance_manager.get_logic(client_id)

    # Evitamos que se encolen múltiples trabajos para el mismo cliente.
    if logic.is_publishing:
        return jsonify({"msg": "Un proceso de publicación ya está en ejecución para ti."}), 409
        
    data = request.get_json()
    if not data or 'group_tags' not in data or 'content_tags' not in data:
        return jsonify({"msg": "Faltan etiquetas de grupos o de contenido."}), 400

    # Creamos el trabajo y lo añadimos a la cola.
    job = {
        'client_id': client_id, 
        'task_type': 'publish_to_groups', 
        'data': {
            'group_tags': data['group_tags'],
            'content_tags': data['content_tags']
        }
    }
    job_queue.put(job)
    
    # Actualizamos el estado y notificamos al frontend.
    logic.is_publishing = True
    logic.log_to_panel("✅ Tu solicitud de publicación ha sido añadida a la cola.")
    socketio.emit('publishing_status', {'isPublishing': True}, room=str(client_id))
    
    return jsonify({"msg": "Proceso de publicación encolado."})


@app.route('/api/publishing/stop', methods=['POST'])
@jwt_required()
def stop_publishing():
    client_id_raw = get_jwt().get('sub')
    try:
        client_id = int(client_id_raw)
    except (TypeError, ValueError):
        return jsonify({"msg": "Token inválido."}), 401

    # --- LÍNEA CORREGIDA (para consistencia) ---
    # Aquí también usamos el método get_logic para ser consistentes.
    logic = instance_manager.get_logic(client_id)
    
    if logic.is_publishing:
        logic.is_publishing = False
        logic.log_to_panel("Solicitud de detención recibida. El proceso terminará después de la publicación actual.", "warning")
        return jsonify({"msg": "Se ha solicitado la detención del proceso."})
    
    return jsonify({"msg": "No hay ningún proceso en ejecución para detener."})


# ==============================================================================
# --- WEB SOCKETS E INICIO ---
# ==============================================================================

@socketio.on('join')
def on_join(data):
    """Un cliente se une a su sala privada para recibir logs, validando su token JWT."""
    token = data.get('token')
    client_id = data.get('client_id')
    if not token:
        disconnect()
        return

    try:
        # Validar que el token corresponde al client_id que intenta unirse
        decoded_token = decode_token(token)
        token_client_id = decoded_token['sub']
        if token_client_id == client_id:
            join_room(client_id)
            instance_manager.get_logic(client_id).log_to_panel("Conectado a la consola.")
        else:
            # Si el token es válido pero para otro usuario, se desconecta por seguridad
            disconnect()
    except Exception as e:
        print(f"Error de autenticación de WebSocket: {e}")
        disconnect()

@socketio.on('connect')
def on_connect():
    print("Cliente conectado a WebSocket. Esperando autenticación para unirse a una sala.")

@socketio.on('disconnect')
def on_disconnect():
    print("Cliente desconectado de WebSocket.")

if __name__ == "__main__":
    for i in range(MAX_CONCURRENT_BROWSERS):
        worker_thread = threading.Thread(target=job_worker, daemon=True)
        worker_thread.start()

    print(f"🚀 Iniciando servidor Flask en modo Multi-Inquilino...")
    # Usar eventlet o gevent es recomendado para producción con SocketIO
    socketio.run(app, debug=False, host='0.0.0.0', port=5001)

