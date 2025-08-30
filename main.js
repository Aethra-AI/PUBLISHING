// ======================================================
// ====== BLOQUE DE CÓDIGO PARA AÑADIR (CONFIG API) ======
// ======================================================
// Al principio de main.js
let socket; // Variable global para la conexión WebSocket
const API_URL = 'https://34.55.41.159.sslip.io'; // URL base de tu backend

// Almacena el estado del cliente logueado
let clientState = {
    id: null,
    name: null,
    token: null
};


// Estado global de la aplicación
// Estado global de la aplicación
let appState = {
    data: {
        texts: [],
        images: [],
        groups: [],
        pages: [],
        scheduled_posts: [],
        publication_log: [] // Añadido para el historial
    },
    ui: {
        currentTab: 'dashboard',
        isGroupPublishing: false
    }
};

// ======================================================
// ====== BLOQUE PARA AÑADIR (LÓGICA DE AUTENTICACIÓN) ======
// ======================================================

// --- GESTIÓN DE AUTENTICACIÓN 

// ======================================================
// ====== BLOQUE PARA AÑADIR (función connectWebSocket) ======
// ======================================================
function connectWebSocket() {
    // Si ya existe una conexión, la desconectamos primero
    if (socket && socket.connected) {
        socket.disconnect();
    }

    socket = io(API_URL, {
        transports: ['websocket']
    });

    socket.on('connect', () => {
        console.log('✅ Conectado al servidor de logs vía WebSocket.');
        // Una vez conectado, nos autenticamos para unirnos a nuestra sala privada
        socket.emit('join', { 
            token: clientState.token,
            client_id: clientState.id
        });
    });

    // Escuchamos los mensajes de log que envía el servidor
    socket.on('log_message', (msg) => {
        LogManager.addLog(msg.data, msg.type);
    });
    
    // Escuchamos los cambios de estado de la publicación
    socket.on('publishing_status', (data) => {
        console.log(`Estado de publicación recibido: ${data.isPublishing}`);
        appState.ui.isGroupPublishing = data.isPublishing;
        GroupPublishingManager.updatePublishingUI(data.isPublishing);
    });

    socket.on('disconnect', () => {
        console.log('🔌 Desconectado del servidor de logs.');
    });

    socket.on('connect_error', (error) => {
        console.error('❌ Error de conexión WebSocket:', error);
        LogManager.addLog('Error de conexión con la consola.', 'error');
    });
}

async function handleLogin() {
    const email = document.getElementById('email').value.trim();
    const password = document.getElementById('password').value.trim();
    const errorDiv = document.getElementById('login-error');
    const loginButton = document.getElementById('login-button');

    if (!email || !password) {
        errorDiv.textContent = 'Por favor, introduce tu email y contraseña.';
        errorDiv.style.display = 'block';
        return;
    }

    loginButton.disabled = true;
    loginButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Entrando...';
    errorDiv.style.display = 'none';

    try {
        const response = await fetch(`${API_URL}/api/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ email, password })
        });

        const data = await response.json();

        if (response.ok) {
            clientState.token = data.access_token;
            clientState.id = data.clientId;
            clientState.name = data.clientName;
            localStorage.setItem('jwt_token', data.access_token);
            
            showApp();
            await DataManager.loadInitialData();
        } else {
            errorDiv.textContent = data.msg || 'Error al iniciar sesión. Verifica tus credenciales.';
            errorDiv.style.display = 'block';
        }
    } catch (error) {
        console.error('Error de red al iniciar sesión:', error);
        errorDiv.textContent = 'No se pudo conectar con el servidor. Inténtalo más tarde.';
        errorDiv.style.display = 'block';
    } finally {
        loginButton.disabled = false;
        loginButton.innerHTML = '<i class="fas fa-sign-in-alt"></i> Entrar';
    }
}

// --- FUNCIONES DE VISIBILIDAD Y SESIÓN ---

function showApp() {
    document.getElementById('login-container').style.display = 'none';
    document.getElementById('app-container').style.display = 'grid';
    
    const userNameEl = document.getElementById('user-name');
    const userAvatarEl = document.getElementById('user-avatar');
    if (clientState.name) {
        userNameEl.textContent = clientState.name;
        userAvatarEl.textContent = clientState.name.substring(0, 2).toUpperCase();
    }

    // Iniciar conexión WebSocket
    connectWebSocket();
}

function showLogin() {
    document.getElementById('login-container').style.display = 'flex';
    document.getElementById('app-container').style.display = 'none';
    
    clientState = { id: null, name: null, token: null };
    localStorage.removeItem('jwt_token');
    document.getElementById('email').value = '';
    document.getElementById('password').value = '';
}


function handleLogout() {
    if (socket && socket.connected) {
        socket.disconnect();
    }
    showLogin();
    const logPanel = document.getElementById('log-panel');
    logPanel.innerHTML = '<p class="log-info">Sesión cerrada. Inicia sesión para continuar.</p>';
}

// ======================================================
// ====== BLOQUE PARA AÑADIR (función apiRequest) ======
// ======================================================
async function apiRequest(endpoint, method, body = null) {
    const headers = { 'Authorization': `Bearer ${clientState.token}` };
    const config = { method, headers };

    if (body) {
        if (body instanceof FormData) {
            config.body = body;
        } else {
            headers['Content-Type'] = 'application/json';
            config.body = JSON.stringify(body);
        }
    }

    const response = await fetch(`${API_URL}${endpoint}`, config);

    if (!response.ok) {
        if (response.status === 401 || response.status === 422) {
            Utils.showNotification('Sesión Expirada', 'Por favor, inicia sesión de nuevo.', 'warning');
            handleLogout();
        }
        const errorData = await response.json();
        throw new Error(errorData.msg || `Error en la petición a ${endpoint}`);
    }

    if (response.status === 204 || response.headers.get("content-length") === "0") {
        return { success: true };
    }
    return response.json();
}


// Utilidades
const Utils = {
    // Mostrar/ocultar loading
    showLoading(show = true) {
        const overlay = document.getElementById('loading-overlay');
        if (show) {
            overlay.classList.add('show');
        } else {
            overlay.classList.remove('show');
        }
    },

    // Mostrar notificaciones
    showNotification(title, message, type = 'success') {
        const notification = document.getElementById('notification');
        const titleEl = notification.querySelector('.notification-title');
        const messageEl = notification.querySelector('.notification-content div:last-child');
        const iconEl = notification.querySelector('.notification-icon i');

        titleEl.textContent = title;
        messageEl.textContent = message;
        
        // Cambiar icono según el tipo
        switch(type) {
            case 'success':
                iconEl.className = 'fas fa-check';
                break;
            case 'error':
                iconEl.className = 'fas fa-exclamation-triangle';
                break;
            case 'warning':
                iconEl.className = 'fas fa-exclamation-circle';
                break;
            default:
                iconEl.className = 'fas fa-info';
        }

        notification.className = `notification ${type}`;
        notification.classList.add('show');

        // Auto-ocultar después de 5 segundos
        setTimeout(() => {
            notification.classList.remove('show');
        }, 5000);
    },

    // Formatear fecha
    formatDateTime(dateString) {
        if (!dateString) return 'N/A';
        const date = new Date(dateString);
        return date.toLocaleString('es-ES');
    },

    // Truncar texto
    truncateText(text, maxLength = 100) {
        if (!text) return '';
        return text.length > maxLength ? text.substring(0, maxLength) + '...' : text;
    },

    // Validar URL
    isValidUrl(string) {
        try {
            new URL(string);
            return true;
        } catch (_) {
            return false;
        }
    }
};

// Manejo de datos
const DataManager = {
    // Cargar datos iniciales
    async loadInitialData() {
        // 1. Verificación de seguridad: si no hay token, no continuar.
        if (!clientState.token) {
            console.error("loadInitialData fue llamado sin un token. Redirigiendo al login.");
            showLogin(); // Muestra la pantalla de login.
            return;
        }

        try {
            Utils.showLoading(true);
            
            // 2. Realiza la petición a la API con el token de autorización.
            const response = await fetch(`${API_URL}/api/data/initial`, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${clientState.token}`
                }
            });

            // 3. Procesa la respuesta del servidor.
            if (response.ok) {
                const data = await response.json();
                appState.data = data; // Almacena los datos del cliente en el estado de la app.
                
                // Actualiza el nombre del cliente en la UI, por si se reanudó la sesión.
                if (data.client_info && data.client_info.name) {
                    clientState.name = data.client_info.name;
                    clientState.id = data.client_info.id;
                    const userNameEl = document.getElementById('user-name');
                    const userAvatarEl = document.getElementById('user-avatar');
                    userNameEl.textContent = clientState.name;
                    userAvatarEl.textContent = clientState.name.substring(0, 2).toUpperCase();
                }

                this.updateUI(); // Dibuja todos los datos en las tablas.
                this.updateStatus(true);
                Utils.showNotification('Datos Sincronizados', 'Tu información se ha cargado correctamente.', 'success');
            } else {
                // 4. Manejo de errores, especialmente de sesión expirada.
                if (response.status === 401 || response.status === 422) {
                    // El token es inválido o ha expirado.
                    Utils.showNotification('Sesión Expirada', 'Por favor, inicia sesión de nuevo.', 'warning');
                    handleLogout(); // Cierra la sesión y muestra la pantalla de login.
                } else {
                    // Otro tipo de error del servidor (ej. 500 Internal Server Error).
                    const errorData = await response.json();
                    throw new Error(errorData.msg || `Error del servidor: ${response.status}`);
                }
            }

        } catch (error) {
            console.error('Error crítico al cargar datos iniciales:', error);
            Utils.showNotification('Error de Conexión', 'No se pudieron cargar los datos. Revisa tu conexión.', 'error');
            this.updateStatus(false);
            handleLogout(); // Como medida de seguridad, cierra la sesión si hay un error de red.
        } finally {
            Utils.showLoading(false);
        }
    },

    // Actualizar interfaz con los datos
    updateUI() {
        this.updateStats();
        this.updateTextsTable();
        this.updateImagesTable();
        this.updateGroupsTable();
        this.updatePagesTable();
        this.updateScheduledPostsTable();
        this.updateSelects();
        this.updateHistoryTable();
    },

    // Actualizar estadísticas del dashboard
    updateStats() {
        document.getElementById('total-texts').textContent = appState.data.texts?.length || 0;
        document.getElementById('total-images').textContent = appState.data.images?.length || 0;
        document.getElementById('total-groups').textContent = appState.data.groups?.length || 0;
        document.getElementById('total-scheduled').textContent = appState.data.scheduled_posts?.length || 0;

        // Actualizar contadores en las pestañas
        document.getElementById('texts-count').textContent = `${appState.data.texts?.length || 0} textos`;
        document.getElementById('images-count').textContent = `${appState.data.images?.length || 0} imágenes`;
        document.getElementById('groups-count').textContent = `${appState.data.groups?.length || 0} grupos`;
        document.getElementById('pages-count').textContent = `${appState.data.pages?.length || 0} páginas`;
        document.getElementById('scheduled-count').textContent = `${appState.data.scheduled_posts?.length || 0} programadas`;
    },


        // Actualizar tabla de textos
    updateTextsTable() {
        const tbody = document.getElementById('texts-table-body');
        if (!appState.data.texts || appState.data.texts.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No hay textos disponibles</td></tr>';
            return;
        }

        tbody.innerHTML = appState.data.texts.map(text => {
            const usageCount = text.usage_count || 0;
            let usageClass = '';
            if (usageCount >= 7 && usageCount < 10) {
                usageClass = 'tag-warning';
            } else if (usageCount >= 10) {
                usageClass = 'tag-danger';
            }
            
            // Escapar el contenido para que no rompa el HTML en el onclick
            const escapedContent = text.content.replace(/`/g, '\\`').replace(/\$/g, '\\$');

            return `
                <tr>
                    <td>${text.id}</td>
                    <td style="max-width: 300px; word-wrap: break-word;">${Utils.truncateText(text.content)}</td>
                    <td>
                        ${(text.ai_tags || '').split(',').filter(tag => tag.trim()).map(tag => 
                            `<span class="tag">${tag.trim()}</span>`
                        ).join('')}
                    </td>
                    <td>
                        <span class="tag ${usageClass}">${usageCount}</span>
                    </td>
                    <td class="actions">
                        <button class="btn btn-sm btn-icon btn-secondary" onclick="UIManager.showTextEditModal(${text.id}, \`${escapedContent}\`)">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="btn btn-sm btn-icon btn-danger" onclick="DataManager.deleteItem('texts', ${text.id})">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
    },

            
  
    updateImagesTable: function() {
        const tbody = document.getElementById('images-table-body');
        if (!appState.data.images || appState.data.images.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">No hay imágenes disponibles</td></tr>';
            return;
        }

        tbody.innerHTML = appState.data.images.map(image => {
            const usageCount = image.usage_count || 0;
            let usageClass = '';
            if (usageCount >= 7 && usageCount < 10) usageClass = 'tag-warning';
            else if (usageCount >= 10) usageClass = 'tag-danger';

            // Construye la URL completa de la imagen en el servidor
            const imageUrl = `${API_URL}/uploads/client_${clientState.id}/${image.path.split(/[\\/]/).pop()}`;

            return `
                <tr>
                    <td>${image.id}</td>
                    <td>
                        <img 
                            src="${imageUrl}" 
                            class="image-preview" 
                            style="cursor: pointer;"
                            onclick="UIManager.showImageModal('${imageUrl}')"
                            onerror="this.style.display='none'; this.nextElementSibling.style.display='block'">
                        <div style="display:none; color:var(--text-muted); font-size:0.8em;">Error</div>
                    </td>
                    <td style="max-width: 250px; word-wrap: break-word;">${Utils.truncateText(image.path.split(/[\\/]/).pop())}</td>
                    <td>
                        ${(image.manual_tags || '').split(',').filter(tag => tag.trim()).map(tag => 
                            `<span class="tag">${tag.trim()}</span>`
                        ).join('')}
                    </td>
                    <td><span class="tag ${usageClass}">${usageCount}</span></td>
                    <td class="actions">
                        <button class="btn btn-sm btn-icon btn-danger" onclick="DataManager.deleteItem('images', ${image.id})">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
    },

    // Actualizar tabla de grupos
    updateGroupsTable() {
        const tbody = document.getElementById('groups-table-body');
        if (!appState.data.groups || appState.data.groups.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">No hay grupos disponibles</td></tr>';
            return;
        }

        tbody.innerHTML = appState.data.groups.map(group => `
            <tr>
                <td>${group.id}</td>
                <td style="max-width: 300px; word-wrap: break-word;">
                    <a href="${group.url}" target="_blank" style="color: var(--primary);">${Utils.truncateText(group.url)}</a>
                </td>
                <td>
                    ${(group.tags || '').split(',').filter(tag => tag.trim()).map(tag => 
                        `<span class="tag">${tag.trim()}</span>`
                    ).join('')}
                </td>
                <td class="actions">
                    <button class="btn btn-sm btn-icon btn-danger" onclick="DataManager.deleteItem('groups', ${group.id})">
                        <i class="fas fa-trash"></i>
                    </button>
                </td>
            </tr>
        `).join('');
    },

    // Actualizar tabla de páginas
    updatePagesTable() {
        const tbody = document.getElementById('pages-table-body');
        if (!appState.data.pages || appState.data.pages.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">No hay páginas disponibles</td></tr>';
            return;
        }

        tbody.innerHTML = appState.data.pages.map(page => `
            <tr>
                <td>${page.id}</td>
                <td>${page.name}</td>
                <td style="max-width: 300px; word-wrap: break-word;">
                    <a href="${page.page_url}" target="_blank" style="color: var(--primary);">${Utils.truncateText(page.page_url)}</a>
                </td>
                <td class="actions">
                    <button class="btn btn-sm btn-icon btn-danger" onclick="DataManager.deleteItem('pages', ${page.id})">
                        <i class="fas fa-trash"></i>
                    </button>
                </td>
            </tr>
        `).join('');
    },

    // Actualizar tabla de publicaciones programadas
    updateScheduledPostsTable: function() {
        const tbody = document.getElementById('scheduled-posts-table-body');
        if (!appState.data.scheduled_posts || appState.data.scheduled_posts.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No hay publicaciones programadas</td></tr>';
            return;
        }

        tbody.innerHTML = appState.data.scheduled_posts.map(post => {
            let statusClass = 'tag-warning';
            if (post.status === 'completed') statusClass = 'tag-success';
            else if (post.status === 'failed') statusClass = 'tag-danger';
            
            return `
                <tr>
                    <td>${post.id}</td>
                    <td>${post.page_name || 'N/A'}</td>
                    <td style="max-width: 250px; word-wrap: break-word;">${Utils.truncateText(post.text_content)}</td>
                    <td>
                        ${post.image_path ? 
                            `<img src="${API_URL}/uploads/client_${clientState.id}/${post.image_path.split(/[\\/]/).pop()}" class="image-preview" onerror="this.style.display='none'">` : 
                            'Sin imagen'
                        }
                    </td>
                    <td>${Utils.formatDateTime(post.publish_at)}</td>
                    <td><span class="tag ${statusClass}">${post.status}</span></td>
                    <td class="actions">
                        <button class="btn btn-sm btn-icon btn-danger" onclick="DataManager.deleteItem('scheduled_posts', ${post.id})">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
    },
    // Actualizar selects
    updateSelects() {
        // Select de páginas para el programador
        const pageSelect = document.getElementById('schedule-page-select');
        pageSelect.innerHTML = '<option value="">Selecciona una página...</option>';
        if (appState.data.pages) {
            appState.data.pages.forEach(page => {
                pageSelect.innerHTML += `<option value="${page.id}">${page.name}</option>`;
            });
        }

        // Select de imágenes para el programador
        const imageSelect = document.getElementById('schedule-image-select');
        imageSelect.innerHTML = '<option value="">Sin imagen</option>';
        if (appState.data.images) {
            appState.data.images.forEach(image => {
                const filename = image.path.split('\\').pop().split('/').pop();
                imageSelect.innerHTML += `<option value="${image.id}">${filename}</option>`;
            });
        }
    },

    // Actualizar estado de conexión
    updateStatus(connected) {
        const statusDot = document.getElementById('status-dot');
        const statusText = document.getElementById('status-text');
        
        if (connected) {
            statusDot.className = 'status-dot active';
            statusText.textContent = 'Conectado';
        } else {
            statusDot.className = 'status-dot inactive';
            statusText.textContent = 'Desconectado';
        }
    },

    // Métodos para eliminar elementos
        // ======================================================
    // ====== BLOQUE PARA REEMPLAZAR (FUNCIONES DELETE) ======
    // ======================================================
    async deleteItem(type, id) {
        if (!confirm(`¿Estás seguro de que deseas eliminar este elemento de tipo '${type}'?`)) return;
        
        try {
            Utils.showLoading(true);
            const result = await apiRequest(`/api/items/${type}/${id}`, 'DELETE');
            
            // Recargamos todos los datos para mantener la consistencia
            await this.loadInitialData(); 
            
            Utils.showNotification('Elemento eliminado', result.msg || "El elemento fue eliminado.", 'success');

        } catch (error) {
            console.error(`Error eliminando ${type}:`, error);
            Utils.showNotification('Error', `No se pudo eliminar el elemento: ${error.message}`, 'error');
        } finally {
            Utils.showLoading(false);
        }
    },

    // Las funciones antiguas ahora llaman a la nueva genérica
    deleteText: function(id) { this.deleteItem('texts', id); },
    deleteImage: function(id) { this.deleteItem('images', id); },
    deleteGroup: function(id) { this.deleteItem('groups', id); },
    deletePage: function(id) { this.deleteItem('pages', id); },
    deleteScheduledPost: function(id) { this.deleteItem('scheduled_posts', id); },
    updateHistoryTable() {
        const tbody = document.getElementById('history-table-body');
        const logs = appState.data.publication_log;

        if (!logs || logs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No hay actividades recientes en el historial.</td></tr>';
            return;
        }

        tbody.innerHTML = logs.map(log => {
            const statusClass = log.status === 'Success' ? 'tag-success' : 'tag-danger';
            const statusText = log.status === 'Success' ? 'Completado' : 'Fallido';
            
            const actionText = log.target_type === 'group' ? 'Publicación en grupo' : 'Publicación en página';
            
            let detailsHtml = 'N/A';
            if (log.published_post_url) {
                detailsHtml = `<a href="${log.published_post_url}" target="_blank" style="color: var(--primary);">Ver Publicación</a>`;
            } else if (log.status === 'Failed') {
                detailsHtml = 'No se pudo publicar.';
            }

            return `
                <tr>
                    <td>${Utils.formatDateTime(log.timestamp)}</td>
                    <td>${actionText}</td>
                    <td style="max-width: 250px; word-wrap: break-word;">
                        <a href="${log.target_url}" target="_blank">${Utils.truncateText(log.target_url, 40)}</a>
                    </td>
                    <td><span class="tag ${statusClass}">${statusText}</span></td>
                    <td>${detailsHtml}</td>
                </tr>
            `;
        }).join('');
    },
};



// ======================================================
// ====== BLOQUE PARA REEMPLAZAR (ContentManager con sintaxis explícita) ======
// ======================================================

const ContentManager = {
    // Añadir texto manual
    addManualText: async function() {
        const content = document.getElementById('manual-text-input').value.trim();
        if (!content) {
            Utils.showNotification('Entrada no válida', 'Por favor ingresa un texto.', 'warning');
            return;
        }

        try {
            Utils.showLoading(true);
            const updatedTexts = await apiRequest('/api/texts', 'POST', { content: content });
            appState.data.texts = updatedTexts;
            DataManager.updateTextsTable();
            DataManager.updateStats();
            document.getElementById('manual-text-input').value = '';
            Utils.showNotification('Éxito', 'El texto se agregó correctamente.', 'success');
        } catch (error) {
            console.error('Error añadiendo texto:', error);
            Utils.showNotification('Error', `No se pudo añadir el texto: ${error.message}`, 'error');
        } finally {
            Utils.showLoading(false);
        }
    },

    // Generar textos con IA
    generateAiTexts: async function() {
        const topic = document.getElementById('ai-topic-input').value.trim();
        const count = parseInt(document.getElementById('ai-count-input').value) || 5;

        if (!topic) {
            Utils.showNotification('Entrada no válida', 'Por favor ingresa un tema para la IA.', 'warning');
            return;
        }

        try {
            Utils.showLoading(true);
            const updatedTexts = await apiRequest('/api/texts/generate-ai', 'POST', { topic: topic, count: count });
            appState.data.texts = updatedTexts;
            DataManager.updateTextsTable();
            DataManager.updateStats();
            document.getElementById('ai-topic-input').value = '';
            Utils.showNotification('Éxito', `Se generaron y añadieron ${count} textos con IA.`, 'success');
        } catch (error) {
            console.error('Error generando textos con IA:', error);
            Utils.showNotification('Error', `No se pudieron generar los textos: ${error.message}`, 'error');
        } finally {
            Utils.showLoading(false);
        }
    },

    // Añadir imágenes (ahora solo dispara el clic)
    addImages: function() {
        const fileInput = document.getElementById('file-upload-input');
        fileInput.click();
    },

    // Esta es la función que maneja la subida real
    uploadSelectedImages: async function(event) {
        const files = event.target.files;
        if (!files || files.length === 0) {
            return;
        }

        const tags = document.getElementById('image-tags-input').value.trim();
        
        const formData = new FormData();
        for (const file of files) {
            formData.append('images', file);
        }
        formData.append('tags', tags);

        try {
            Utils.showLoading(true);
            const updatedImages = await apiRequest('/api/images/upload', 'POST', formData);
            appState.data.images = updatedImages;
            DataManager.updateImagesTable();
            DataManager.updateStats();
            DataManager.updateSelects();
            document.getElementById('image-tags-input').value = '';
            Utils.showNotification('Éxito', 'Las imágenes se subieron y guardaron correctamente.', 'success');
        } catch (error) {
            console.error('Error subiendo imágenes:', error);
            Utils.showNotification('Error', `No se pudieron subir las imágenes: ${error.message}`, 'error');
        } finally {
            event.target.value = null;
            Utils.showLoading(false);
        }
    }
};




// Manejo de destinos

const DestinationManager = {
    addSingleGroup: async function() {
        const url = document.getElementById('group-url-input').value.trim();
        const tags = document.getElementById('group-tags-single-input').value.trim();
        if (!url || !Utils.isValidUrl(url)) {
            Utils.showNotification('Entrada no válida', 'URL de grupo no válida.', 'warning'); return;
        }
        try {
            Utils.showLoading(true);
            // CORRECCIÓN: Apunta al endpoint correcto /api/groups
            const updatedData = await apiRequest('/api/groups', 'POST', { url, tags });
            appState.data.groups = updatedData;
            DataManager.updateGroupsTable(); DataManager.updateStats();
            document.getElementById('group-url-input').value = '';
            document.getElementById('group-tags-single-input').value = '';
            Utils.showNotification('Éxito', 'Grupo agregado.', 'success');
        } catch (error) { Utils.showNotification('Error', `No se pudo añadir: ${error.message}`, 'error'); } 
        finally { Utils.showLoading(false); }
    },
    importBulkGroups: async function() {
        const urlsText = document.getElementById('bulk-groups-input').value.trim();
        const tags = document.getElementById('bulk-tags-input').value.trim();
        if (!urlsText) {
            Utils.showNotification('Entrada no válida', 'Ingresa al menos una URL.', 'warning'); return;
        }
        const urls = urlsText.split('\n').map(u => u.trim()).filter(Boolean);
        try {
            Utils.showLoading(true);
            // CORRECCIÓN: Apunta al endpoint correcto /api/groups/bulk
            const updatedData = await apiRequest('/api/groups/bulk', 'POST', { urls, tags });
            appState.data.groups = updatedData;
            DataManager.updateGroupsTable(); DataManager.updateStats();
            document.getElementById('bulk-groups-input').value = '';
            document.getElementById('bulk-tags-input').value = '';
            Utils.showNotification('Éxito', 'Grupos importados.', 'success');
        } catch (error) { Utils.showNotification('Error', `Error al importar: ${error.message}`, 'error'); }
        finally { Utils.showLoading(false); }
    },
    addPage: async function() {
        const name = document.getElementById('page-name-input').value.trim();
        const page_url = document.getElementById('page-url-input').value.trim();
        if (!name || !page_url || !Utils.isValidUrl(page_url)) {
            Utils.showNotification('Entrada no válida', 'Datos de página no válidos.', 'warning'); return;
        }
        try {
            Utils.showLoading(true);
            // CORRECCIÓN: Apunta al endpoint correcto /api/pages
            const updatedData = await apiRequest('/api/pages', 'POST', { name, page_url });
            appState.data.pages = updatedData;
            DataManager.updatePagesTable(); DataManager.updateStats(); DataManager.updateSelects();
            document.getElementById('page-name-input').value = '';
            document.getElementById('page-url-input').value = '';
            Utils.showNotification('Éxito', 'Página agregada.', 'success');
        } catch (error) { Utils.showNotification('Error', `No se pudo añadir: ${error.message}`, 'error'); }
        finally { Utils.showLoading(false); }
    }
};



// Manejo del programador

const SchedulerManager = {
    getContentSuggestion: async function() {
        const pageId = document.getElementById('schedule-page-select').value;
        if (!pageId) {
            Utils.showNotification('Acción requerida', 'Selecciona una página.', 'warning'); return;
        }
        try {
            Utils.showLoading(true);
            // CORRECCIÓN: Asumimos este endpoint, asegúrate que exista en main.py
            const suggestion = await apiRequest('/api/content/suggestion', 'POST', { page_id: parseInt(pageId) });
            if (suggestion.success && suggestion.text && suggestion.image) {
                document.getElementById('schedule-text-content').value = suggestion.text.content;
                document.getElementById('schedule-image-select').value = suggestion.image.id;
                Utils.showNotification('Sugerencia aplicada', 'Contenido cargado.', 'success');
            } else {
                Utils.showNotification('Sin sugerencias', suggestion.message || 'No se encontraron sugerencias.', 'warning');
            }
        } catch (error) { Utils.showNotification('Error', `No se pudo sugerir: ${error.message}`, 'error'); }
        finally { Utils.showLoading(false); }
    },
    schedulePost: async function() {
        const pageId = document.getElementById('schedule-page-select').value;
        const publishAt = document.getElementById('schedule-datetime').value;
        const textContent = document.getElementById('schedule-text-content').value.trim();
        const imageId = document.getElementById('schedule-image-select').value || null;

        if (!pageId || !publishAt || !textContent) {
            Utils.showNotification('Campos requeridos', 'Página, fecha y texto son obligatorios.', 'warning'); return;
        }
        const data = {
            page_id: parseInt(pageId),
            publish_at: new Date(publishAt).toISOString(),
            text_content: textContent,
            image_id: imageId ? parseInt(imageId) : null
        };
        try {
            Utils.showLoading(true);
            // CORRECCIÓN: Apunta al endpoint correcto /api/scheduled_posts
            const updatedData = await apiRequest('/api/scheduled_posts', 'POST', data);
            appState.data.scheduled_posts = updatedData;
            DataManager.updateScheduledPostsTable(); DataManager.updateStats();
            document.getElementById('schedule-page-select').value = '';
            document.getElementById('schedule-datetime').value = '';
            document.getElementById('schedule-text-content').value = '';
            document.getElementById('schedule-image-select').value = '';
            Utils.showNotification('Éxito', 'Publicación programada.', 'success');
        } catch (error) { Utils.showNotification('Error', `No se pudo programar: ${error.message}`, 'error'); } 
        finally { Utils.showLoading(false); }
    }
};

// Manejo de publicación en grupos

const GroupPublishingManager = {
    startGroupPublishing: async function() {
        const groupTags = document.getElementById('group-tags-input').value.trim();
        const contentTags = document.getElementById('content-tags-input').value.trim();
        if (!groupTags || !contentTags) {
            Utils.showNotification('Campos requeridos', 'Por favor, define etiquetas para grupos y contenido.', 'warning');
            return;
        }
        try {
            // No necesitamos `Utils.showLoading(true)` porque el backend
            // responderá inmediatamente. La UI se actualizará vía WebSocket.
            const result = await apiRequest('/api/publishing/start', 'POST', { group_tags: groupTags, content_tags: contentTags });
            Utils.showNotification('Solicitud Enviada', result.msg, 'success');
        } catch (error) {
            Utils.showNotification('Error', `No se pudo iniciar la publicación: ${error.message}`, 'error');
        }
    },
    stopGroupPublishing: async function() {
        try {
            const result = await apiRequest('/api/publishing/stop', 'POST');
            Utils.showNotification('Solicitud Enviada', result.msg, 'success');
        } catch (error) {
            Utils.showNotification('Error', `No se pudo detener la publicación: ${error.message}`, 'error');
        }
    },
    updatePublishingUI: function(isPublishing) {
        const startBtn = document.getElementById('start-group-publishing');
        const stopBtn = document.getElementById('stop-group-publishing');
        if (isPublishing) {
            startBtn.style.display = 'none';
            stopBtn.style.display = 'inline-flex';
            startBtn.disabled = true;
        } else {
            startBtn.style.display = 'inline-flex';
            stopBtn.style.display = 'none';
            startBtn.disabled = false;
        }
    }
};

// Manejo de logs
const LogManager = {
    // Limpiar logs
    clearLogs() {
        const logPanel = document.getElementById('log-panel');
        logPanel.innerHTML = '<p class="log-info">Logs limpiados.</p>';
    },

    // Añadir log (esta función será llamada desde Python)
    addLog(message, type = 'info') {
        const logPanel = document.getElementById('log-panel');
        const logEntry = document.createElement('p');
        logEntry.className = `log-${type}`;
        logEntry.textContent = message;
        logPanel.appendChild(logEntry);
        logPanel.scrollTop = logPanel.scrollHeight;
    }
};

// ======================================================
// ====== BLOQUE PARA AÑADIR (EL UIManager COMPLETO) ======
// ======================================================

const UIManager = {
    init: function() {
        this.setupNavigation();
        this.setupTheme();
        this.setupMobileMenu();
        this.setupEventListeners();
        this.setupNotifications();
    },

    setupNavigation: function() {
        const navLinks = document.querySelectorAll('.nav-link');
        const tabContents = document.querySelectorAll('.tab-content');
        navLinks.forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const tabId = link.dataset.tab;
                navLinks.forEach(l => l.classList.remove('active'));
                link.classList.add('active');
                tabContents.forEach(t => t.classList.remove('active'));
                document.getElementById(tabId).classList.add('active');
                appState.ui.currentTab = tabId;
                if (window.innerWidth < 992) {
                    document.getElementById('sidebar').classList.remove('active');
                }
            });
        });
    },

    setupTheme: function() {
        const themeToggle = document.getElementById('theme-toggle');
        const currentTheme = localStorage.getItem('theme') || 'dark';
        document.body.setAttribute('data-theme', currentTheme);
        themeToggle.innerHTML = currentTheme === 'dark' ? '<i class="fas fa-moon"></i>' : '<i class="fas fa-sun"></i>';
        themeToggle.addEventListener('click', () => {
            const newTheme = document.body.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            document.body.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            themeToggle.innerHTML = newTheme === 'dark' ? '<i class="fas fa-moon"></i>' : '<i class="fas fa-sun"></i>';
        });
    },

    setupMobileMenu: function() {
        const mobileToggle = document.getElementById('mobile-menu-toggle');
        const sidebar = document.getElementById('sidebar');
        mobileToggle.addEventListener('click', () => sidebar.classList.toggle('active'));
        document.addEventListener('click', (e) => {
            if (window.innerWidth < 992 && !sidebar.contains(e.target) && !mobileToggle.contains(e.target)) {
                sidebar.classList.remove('active');
            }
        });
    },

    setupEventListeners: function() {
        // --- LÓGICA DEL MODAL ---
        const modal = document.getElementById('generic-modal');
        const closeBtn = modal.querySelector('.modal-close-btn');
        closeBtn.onclick = () => UIManager.closeModal();
        window.onclick = (event) => {
            if (event.target == modal) UIManager.closeModal();
        };

        // --- LÓGICA DE AUTENTICACIÓN ---
        document.getElementById('login-button').addEventListener('click', handleLogin);
        document.getElementById('logout-button').addEventListener('click', handleLogout);
        document.getElementById('password').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') handleLogin();
        });

        // --- GESTIÓN DE CONTENIDO ---
        document.getElementById('add-manual-text').addEventListener('click', () => ContentManager.addManualText());
        document.getElementById('generate-ai-texts').addEventListener('click', () => ContentManager.generateAiTexts());
        document.getElementById('add-images').addEventListener('click', () => ContentManager.addImages());
        document.getElementById('file-upload-input').addEventListener('change', (event) => ContentManager.uploadSelectedImages(event));

        // --- GESTIÓN DE DESTINOS ---
        document.getElementById('add-single-group').addEventListener('click', () => DestinationManager.addSingleGroup());
        document.getElementById('import-bulk-groups').addEventListener('click', () => DestinationManager.importBulkGroups());
        document.getElementById('add-page').addEventListener('click', () => DestinationManager.addPage());

        // --- PROGRAMADOR ---
        document.getElementById('get-content-suggestion').addEventListener('click', () => SchedulerManager.getContentSuggestion());
        document.getElementById('schedule-post').addEventListener('click', () => SchedulerManager.schedulePost());

        // --- PUBLICACIÓN EN GRUPOS ---
        document.getElementById('start-group-publishing').addEventListener('click', () => GroupPublishingManager.startGroupPublishing());
        document.getElementById('stop-group-publishing').addEventListener('click', () => GroupPublishingManager.stopGroupPublishing);

        // --- VARIOS ---
        document.getElementById('refresh-content').addEventListener('click', () => DataManager.loadInitialData());
        document.getElementById('refresh-destinations').addEventListener('click', () => DataManager.loadInitialData());
        document.getElementById('refresh-scheduler').addEventListener('click', () => DataManager.loadInitialData());
        document.getElementById('clear-log').addEventListener('click', () => LogManager.clearLogs());
    },

    setupNotifications: function() {
        const notification = document.getElementById('notification');
        const closeBtn = notification.querySelector('.notification-close');
        closeBtn.addEventListener('click', () => notification.classList.remove('show'));
    },

    openModal: function() {
        document.getElementById('generic-modal').style.display = 'block';
    },

    closeModal: function() {
        document.getElementById('generic-modal').style.display = 'none';
        document.getElementById('modal-body').innerHTML = '';
    },
    
    showImageModal: function(imageSrc) {
        const modalBody = document.getElementById('modal-body');
        modalBody.innerHTML = `<img src="${imageSrc}" alt="Vista previa de imagen">`;
        this.openModal();
    },

    showTextEditModal: function(id, content) {
        const modalBody = document.getElementById('modal-body');
        modalBody.innerHTML = `
            <h3 style="margin-bottom: 15px;">Editar Texto</h3>
            <textarea id="text-edit-textarea" class="form-control" style="min-height: 250px;">${content}</textarea>
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="UIManager.closeModal()">Cancelar</button>
                <button class="btn btn-primary" onclick="UIManager.saveTextUpdate(${id})">Guardar Cambios</button>
            </div>
        `;
        this.openModal();
    },

    saveTextUpdate: async function(id) {
        const newContent = document.getElementById('text-edit-textarea').value.trim();
        if (!newContent) {
            Utils.showNotification('Error', 'El contenido no puede estar vacío.', 'warning');
            return;
        }
        try {
            Utils.showLoading(true);
            const updatedTexts = await apiRequest(`/api/texts/${id}`, 'PUT', { content: newContent });
            appState.data.texts = updatedTexts;
            DataManager.updateTextsTable();
            UIManager.closeModal();
            Utils.showNotification('Texto actualizado', 'El texto se actualizó correctamente.', 'success');
        } catch (error) {
            Utils.showNotification('Error', `No se pudo guardar el texto: ${error.message}`, 'error');
        } finally {
            Utils.showLoading(false);
        }
    }
};


document.addEventListener('DOMContentLoaded', async () => {
    UIManager.init(); // ¡ESTA LÍNEA ES CRÍTICA! Activa todos los botones.
    
    const token = localStorage.getItem('jwt_token');
    if (token) {
        clientState.token = token;
        showApp();
        await DataManager.loadInitialData();
    } else {
        showLogin();
    }

    const now = new Date();
    const localISOTime = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    document.getElementById('schedule-datetime').min = localISOTime;
});

// Manejo de errores globales
window.addEventListener('error', (e) => {
    console.error('Error global:', e.error);
    Utils.showNotification('Error del sistema', 'Se ha producido un error inesperado', 'error');
});

window.addEventListener('unhandledrejection', (e) => {
    console.error('Promesa rechazada:', e.reason);
    Utils.showNotification('Error del sistema', 'Se ha producido un error de conexión', 'error');
});

