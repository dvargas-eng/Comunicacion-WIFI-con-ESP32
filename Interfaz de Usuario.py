import threading
import queue
import re
import time
import sys

import serial
import serial.tools.list_ports

import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText


BAUD = 115200

# --------- Expresiones regulares para parsear la salida del ESP32 ----------
RE_FOUND = re.compile(r"Se encontraron\s+(\d+)\s+redes", re.IGNORECASE)
RE_NET = re.compile(
    r"^\s*(\d+)\)\s+(.+?)\s+\(RSSI:\s*(-?\d+)\s*dBm\)\s+(Abierta|Segura)\s+Canal:(\d+)",
    re.IGNORECASE,
)
RE_IP_LOCAL = re.compile(r"IP local:\s*([0-9.]+)")
RE_GATEWAY = re.compile(r"Gateway:\s*([0-9.]+)")
RE_SUBMASK = re.compile(r"(?:Submask|Subnet|Máscara|Mask):\s*([0-9.]+)", re.IGNORECASE)
RE_ACTIVE = re.compile(r"Dispositivo activo:\s*([0-9.]+)")
RE_NEED_PASS = re.compile(r"Ingrese la CONTRASEÑA", re.IGNORECASE)
RE_SELECTED = re.compile(r"Seleccionada:\s*(.*)", re.IGNORECASE)


class ESP32WiFiGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ESP32 WiFi Manager - Interfaz Moderna")
        self.geometry("1200x800")
        self.minsize(1000, 700)
        
        # Configurar tema oscuro moderno
        self._setup_modern_theme()

        # ---- Estado ----
        self.ser = None
        self.reader_thread = None
        self.stop_event = threading.Event()
        self.msg_q = queue.Queue()

        self.num_networks_expected = 0
        self.networks = {}  # idx(int 1..N) -> dict(ssid, rssi, security, channel)
        self.waiting_password = False
        self.connected = False

        # ---- UI ----
        self._build_modern_ui()

        # Precargar puertos
        self._refresh_ports()

        # Ciclo para procesar cola de mensajes
        self.after(100, self._process_queue)

    def _setup_modern_theme(self):
        """Configura tema moderno oscuro"""
        self.configure(bg='#1a1a1a')
        
        # Configurar estilos ttk modernos
        style = ttk.Style()
        
        # Tema principal
        style.theme_use('clam')
        
        # Colores modernos
        colors = {
            'bg_primary': '#1a1a1a',      # Fondo principal
            'bg_secondary': '#2d2d2d',    # Fondo secundario
            'bg_accent': '#3d3d3d',       # Fondo de acento
            'accent_blue': '#007acc',     # Azul de acento
            'accent_green': '#4CAF50',    # Verde para éxito
            'accent_red': '#f44336',      # Rojo para error
            'text_primary': '#ffffff',    # Texto principal
            'text_secondary': '#b0b0b0',  # Texto secundario
            'border': '#404040'           # Bordes
        }
        
        # Frame principal
        style.configure('Modern.TFrame', 
                       background=colors['bg_primary'],
                       borderwidth=0)
        
        # Frame secundario
        style.configure('Card.TFrame', 
                       background=colors['bg_secondary'],
                       borderwidth=1,
                       relief='solid',
                       bordercolor=colors['border'])
        
        # Labels
        style.configure('Modern.TLabel',
                       background=colors['bg_primary'],
                       foreground=colors['text_primary'],
                       font=('Segoe UI', 10))
        
        style.configure('Title.TLabel',
                       background=colors['bg_primary'],
                       foreground=colors['text_primary'],
                       font=('Segoe UI', 14, 'bold'))
        
        style.configure('Status.Connected.TLabel',
                       background=colors['bg_primary'],
                       foreground=colors['accent_green'],
                       font=('Segoe UI', 10, 'bold'))
        
        style.configure('Status.Disconnected.TLabel',
                       background=colors['bg_primary'],
                       foreground=colors['accent_red'],
                       font=('Segoe UI', 10, 'bold'))
        
        # Buttons
        style.configure('Modern.TButton',
                       background=colors['accent_blue'],
                       foreground=colors['text_primary'],
                       borderwidth=0,
                       focuscolor='none',
                       font=('Segoe UI', 9, 'bold'),
                       padding=(12, 8))
        
        style.map('Modern.TButton',
                 background=[('active', '#005c99'),
                           ('pressed', '#004d7a'),
                           ('disabled', colors['bg_accent'])])
        
        style.configure('Success.TButton',
                       background=colors['accent_green'],
                       foreground=colors['text_primary'],
                       borderwidth=0,
                       focuscolor='none',
                       font=('Segoe UI', 9, 'bold'),
                       padding=(12, 8))
        
        style.map('Success.TButton',
                 background=[('active', '#45a049'),
                           ('pressed', '#3d8b40')])
        
        style.configure('Danger.TButton',
                       background=colors['accent_red'],
                       foreground=colors['text_primary'],
                       borderwidth=0,
                       focuscolor='none',
                       font=('Segoe UI', 9, 'bold'),
                       padding=(12, 8))
        
        style.map('Danger.TButton',
                 background=[('active', '#d32f2f'),
                           ('pressed', '#b71c1c')])
        
        # Combobox
        style.configure('Modern.TCombobox',
                       background=colors['bg_secondary'],
                       foreground=colors['text_primary'],
                       borderwidth=1,
                       relief='solid',
                       bordercolor=colors['border'],
                       fieldbackground=colors['bg_secondary'],
                       arrowcolor=colors['text_primary'],
                       font=('Segoe UI', 10))
        
        # Entry
        style.configure('Modern.TEntry',
                       background=colors['bg_secondary'],
                       foreground=colors['text_primary'],
                       borderwidth=1,
                       relief='solid',
                       bordercolor=colors['border'],
                       fieldbackground=colors['bg_secondary'],
                       font=('Segoe UI', 10),
                       padding=8)
        
        # Treeview
        style.configure('Modern.Treeview',
                       background=colors['bg_secondary'],
                       foreground=colors['text_primary'],
                       borderwidth=0,
                       fieldbackground=colors['bg_secondary'],
                       font=('Segoe UI', 9))
        
        style.configure('Modern.Treeview.Heading',
                       background=colors['bg_accent'],
                       foreground=colors['text_primary'],
                       borderwidth=1,
                       relief='solid',
                       bordercolor=colors['border'],
                       font=('Segoe UI', 9, 'bold'))
        
        style.map('Modern.Treeview',
                 background=[('selected', colors['accent_blue'])])
        
        # Notebook
        style.configure('Modern.TNotebook',
                       background=colors['bg_primary'],
                       borderwidth=0)
        
        style.configure('Modern.TNotebook.Tab',
                       background=colors['bg_accent'],
                       foreground=colors['text_secondary'],
                       borderwidth=1,
                       relief='solid',
                       bordercolor=colors['border'],
                       padding=(20, 10),
                       font=('Segoe UI', 9, 'bold'))
        
        style.map('Modern.TNotebook.Tab',
                 background=[('selected', colors['accent_blue'])],
                 foreground=[('selected', colors['text_primary'])])
        
        # Checkbutton
        style.configure('Modern.TCheckbutton',
                       background=colors['bg_primary'],
                       foreground=colors['text_primary'],
                       focuscolor='none',
                       font=('Segoe UI', 9))
        
        # LabelFrame
        style.configure('Modern.TLabelframe',
                       background=colors['bg_secondary'],
                       borderwidth=1,
                       relief='solid',
                       bordercolor=colors['border'])
        
        style.configure('Modern.TLabelframe.Label',
                       background=colors['bg_secondary'],
                       foreground=colors['accent_blue'],
                       font=('Segoe UI', 10, 'bold'))

    def _build_modern_ui(self):
        # Container principal con padding
        main_container = ttk.Frame(self, style='Modern.TFrame', padding=20)
        main_container.pack(fill='both', expand=True)
        
        # ============ HEADER ============
        header_frame = ttk.Frame(main_container, style='Card.TFrame', padding=20)
        header_frame.pack(fill='x', pady=(0, 20))
        
        # Título principal
        title_frame = ttk.Frame(header_frame, style='Card.TFrame')
        title_frame.pack(fill='x', pady=(0, 15))
        
        title_label = ttk.Label(title_frame, text="🌐 ESP32 WiFi Manager", 
                               style='Title.TLabel')
        title_label.pack(side='left')
        
        # Status en el header
        self.status_lbl = ttk.Label(title_frame, text="● Desconectado", 
                                   style='Status.Disconnected.TLabel')
        self.status_lbl.pack(side='right')
        
        # Sección de conexión serial
        serial_frame = ttk.Frame(header_frame, style='Card.TFrame')
        serial_frame.pack(fill='x')
        
        # Puerto
        port_label = ttk.Label(serial_frame, text="Puerto Serial:", style='Modern.TLabel')
        port_label.pack(side='left', padx=(0, 8))
        
        self.port_cmb = ttk.Combobox(serial_frame, width=25, state="readonly", 
                                    style='Modern.TCombobox')
        self.port_cmb.pack(side='left', padx=(0, 8))
        
        self.refresh_btn = ttk.Button(serial_frame, text="🔄", width=3, 
                                     command=self._refresh_ports, style='Modern.TButton')
        self.refresh_btn.pack(side='left', padx=(0, 15))
        
        self.connect_btn = ttk.Button(serial_frame, text="Conectar", 
                                     command=self._connect_serial, style='Success.TButton')
        self.connect_btn.pack(side='left', padx=(0, 8))
        
        self.disconnect_btn = ttk.Button(serial_frame, text="Desconectar", 
                                        command=self._disconnect_serial, 
                                        state="disabled", style='Danger.TButton')
        self.disconnect_btn.pack(side='left')
        
        # ============ CONTENIDO PRINCIPAL ============
        content_frame = ttk.Frame(main_container, style='Modern.TFrame')
        content_frame.pack(fill='both', expand=True)
        
        # Panel izquierdo - Redes WiFi
        left_panel = ttk.Frame(content_frame, style='Card.TFrame', padding=20)
        left_panel.pack(side='left', fill='both', expand=True, padx=(0, 10))
        
        # Título de redes
        networks_title = ttk.Label(left_panel, text="📡 Redes WiFi Disponibles", 
                                  style='Title.TLabel')
        networks_title.pack(anchor='w', pady=(0, 15))
        
        # Tabla de redes con scrollbar personalizada
        table_frame = ttk.Frame(left_panel, style='Modern.TFrame')
        table_frame.pack(fill='both', expand=True, pady=(0, 20))
        
        cols = ("#", "SSID", "RSSI", "Seguridad", "Canal")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", 
                                height=12, style='Modern.Treeview')
        
        # Configurar columnas con mejor espaciado
        widths = [60, 280, 80, 100, 70]
        for i, (col, width) in enumerate(zip(cols, widths)):
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor="center", width=width, 
                           stretch=(col == "SSID"), minwidth=50)
        
        # Scrollbar moderna
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        
        # Panel de conexión
        connection_frame = ttk.LabelFrame(left_panel, text="🔐 Configuración de Conexión", 
                                         style='Modern.TLabelframe', padding=20)
        connection_frame.pack(fill='x', pady=(0, 10))
        
        # Instrucciones
        info_label = ttk.Label(connection_frame, 
                              text="Selecciona una red de la tabla y configura la conexión",
                              style='Modern.TLabel')
        info_label.pack(anchor='w', pady=(0, 15))
        
        # Botones de acción
        action_frame = ttk.Frame(connection_frame, style='Modern.TFrame')
        action_frame.pack(fill='x', pady=(0, 15))
        
        self.send_idx_btn = ttk.Button(action_frame, text="📤 Enviar Número", 
                                      command=self._send_selected_index, 
                                      state="disabled", style='Modern.TButton')
        self.send_idx_btn.pack(side='left', padx=(0, 10))
        
        self.conn_mode = tk.BooleanVar(value=False)
        self.conn_chk = ttk.Checkbutton(action_frame, text="Usar protocolo CONN (SSID+pass)", 
                                       variable=self.conn_mode, style='Modern.TCheckbutton')
        self.conn_chk.pack(side='left')
        
        # Contraseña
        pass_frame = ttk.Frame(connection_frame, style='Modern.TFrame')
        pass_frame.pack(fill='x', pady=(0, 15))
        
        pass_label = ttk.Label(pass_frame, text="Contraseña:", style='Modern.TLabel')
        pass_label.pack(side='left', padx=(0, 10))
        
        self.pass_entry = ttk.Entry(pass_frame, width=25, show="•", style='Modern.TEntry')
        self.pass_entry.pack(side='left', padx=(0, 10))
        
        self.show_pass = tk.BooleanVar(value=False)
        ttk.Checkbutton(pass_frame, text="👁 Mostrar", variable=self.show_pass, 
                       command=self._toggle_pass, style='Modern.TCheckbutton').pack(side='left')
        
        # Botón de enviar contraseña
        self.send_pass_btn = ttk.Button(connection_frame, text="🔑 Conectar a Red", 
                                       command=self._send_password_or_conn, 
                                       state="disabled", style='Success.TButton')
        self.send_pass_btn.pack(anchor='w')
        
        # Nota informativa
        note_label = ttk.Label(left_panel, 
                              text="💡 Para re-escanear redes, reinicia el dispositivo ESP32",
                              style='Modern.TLabel')
        note_label.pack(anchor='w', pady=(10, 0))
        
        # ============ PANEL DERECHO ============
        right_panel = ttk.Frame(content_frame, style='Card.TFrame', padding=20)
        right_panel.pack(side='right', fill='both', expand=True, padx=(10, 0))
        
        # Notebook con pestañas
        self.notebook = ttk.Notebook(right_panel, style='Modern.TNotebook')
        self.notebook.pack(fill='both', expand=True)
        
        # ---- TAB: Información de Red ----
        info_tab = ttk.Frame(self.notebook, style='Modern.TFrame', padding=20)
        self.notebook.add(info_tab, text="🌐 Red e IPs")
        
        # Información de conexión
        ip_info_frame = ttk.LabelFrame(info_tab, text="📊 Información de Conexión", 
                                      style='Modern.TLabelframe', padding=20)
        ip_info_frame.pack(fill='x', pady=(0, 20))
        
        self.ip_local_var = tk.StringVar(value="No conectado")
        self.gateway_var = tk.StringVar(value="No disponible")
        self.mask_var = tk.StringVar(value="No disponible")
        
        self._create_info_row(ip_info_frame, "🏠 IP Local:", self.ip_local_var)
        self._create_info_row(ip_info_frame, "🚪 Gateway:", self.gateway_var)
        self._create_info_row(ip_info_frame, "🔒 Máscara:", self.mask_var)
        
        # Dispositivos activos
        devices_frame = ttk.LabelFrame(info_tab, text="🖥 Dispositivos Activos (Ping)", 
                                      style='Modern.TLabelframe', padding=20)
        devices_frame.pack(fill='both', expand=True)
        
        devices_content = ttk.Frame(devices_frame, style='Modern.TFrame')
        devices_content.pack(fill='both', expand=True)
        
        # Lista de dispositivos
        list_frame = ttk.Frame(devices_content, style='Modern.TFrame')
        list_frame.pack(fill='both', expand=True, padx=(0, 15))
        
        self.ip_list = tk.Listbox(list_frame, height=8, 
                                 bg='#2d2d2d', fg='#ffffff', 
                                 selectbackground='#007acc',
                                 font=('Consolas', 10),
                                 borderwidth=1, relief='solid')
        self.ip_list.pack(fill='both', expand=True)
        
        # Botones de dispositivos
        device_btns = ttk.Frame(devices_content, style='Modern.TFrame')
        device_btns.pack(side='right', fill='y')
        
        ttk.Button(device_btns, text="📋 Copiar IPs", command=self._copy_ips,
                  style='Modern.TButton').pack(fill='x', pady=(0, 8))
        ttk.Button(device_btns, text="🗑 Limpiar", command=self._clear_ips,
                  style='Danger.TButton').pack(fill='x')
        
        # ---- TAB: Log Serial ----
        log_tab = ttk.Frame(self.notebook, style='Modern.TFrame', padding=20)
        self.notebook.add(log_tab, text="📝 Log Serial")
        
        log_title = ttk.Label(log_tab, text="💬 Comunicación Serial", style='Title.TLabel')
        log_title.pack(anchor='w', pady=(0, 15))
        
        # Log con estilo moderno
        log_frame = ttk.Frame(log_tab, style='Modern.TFrame')
        log_frame.pack(fill='both', expand=True)
        
        self.log = ScrolledText(log_frame, height=25, wrap="word",
                               bg='#1a1a1a', fg='#00ff00',  # Terminal style
                               font=('Consolas', 9),
                               borderwidth=1, relief='solid')
        self.log.pack(fill='both', expand=True)
        
        # Eventos
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._update_buttons_state())

    def _create_info_row(self, parent, label_text, variable):
        """Crea una fila de información con estilo moderno"""
        row = ttk.Frame(parent, style='Modern.TFrame')
        row.pack(fill='x', pady=8)
        
        label = ttk.Label(row, text=label_text, style='Modern.TLabel', width=15)
        label.pack(side='left')
        
        value_label = ttk.Label(row, textvariable=variable, style='Modern.TLabel',
                               font=('Consolas', 10, 'bold'))
        value_label.pack(side='left', padx=(10, 0))

    # ========================= FUNCIONES ORIGINALES =========================
    # Mantener todas las funciones de lógica intactas
    
    def _refresh_ports(self):
        ports = serial.tools.list_ports.comports()
        items = [p.device for p in ports]
        self.port_cmb["values"] = items
        if items:
            self.port_cmb.current(0)

    def _connect_serial(self):
        if self.ser:
            return
        port = self.port_cmb.get().strip()
        if not port:
            messagebox.showwarning("Puerto", "Selecciona un puerto serial.")
            return
        try:
            self.ser = serial.Serial(port, BAUD, timeout=0.1, write_timeout=0.5)
        except Exception as e:
            messagebox.showerror("Serial", f"No se pudo abrir {port}\n{e}")
            self.ser = None
            return

        # Reset de estado
        self.stop_event.clear()
        self.num_networks_expected = 0
        self.networks.clear()
        self._reload_network_table()
        self.waiting_password = False
        self.connected = False
        self.ip_local_var.set("Conectando...")
        self.gateway_var.set("Obteniendo...")
        self.mask_var.set("Obteniendo...")
        self._clear_ips()

        # Hilo lector
        self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader_thread.start()

        self.status_lbl.config(text=f"● Conectado a {port}", style='Status.Connected.TLabel')
        self.connect_btn.config(state="disabled")
        self.disconnect_btn.config(state="normal")
        self._append_log(f"🔌 Conectado a {port} @ {BAUD} bps\n")

    def _disconnect_serial(self):
        self.stop_event.set()
        time.sleep(0.2)
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.status_lbl.config(text="● Desconectado", style='Status.Disconnected.TLabel')
        self.connect_btn.config(state="normal")
        self.disconnect_btn.config(state="disabled")
        self.ip_local_var.set("No conectado")
        self.gateway_var.set("No disponible") 
        self.mask_var.set("No disponible")
        self._append_log("❌ Desconectado.\n")

    def _reader_loop(self):
        # Lee líneas del Serial y las envía a la cola
        buf = b""
        while not self.stop_event.is_set():
            try:
                data = self.ser.readline() if self.ser else b""
            except Exception:
                data = b""
            if data:
                try:
                    text = data.decode("utf-8", errors="ignore").strip()
                except Exception:
                    text = ""
                if text:
                    self.msg_q.put(text)
            else:
                time.sleep(0.02)

    def _process_queue(self):
        # Procesa mensajes del hilo lector
        while True:
            try:
                line = self.msg_q.get_nowait()
            except queue.Empty:
                break
            self._handle_line(line)
        self.after(80, self._process_queue)

    def _handle_line(self, line: str):
        self._append_log(line + "\n")

        # ¿Cuántas redes?
        m = RE_FOUND.search(line)
        if m:
            try:
                self.num_networks_expected = int(m.group(1))
            except ValueError:
                self.num_networks_expected = 0

        # Entradas de red
        m = RE_NET.search(line)
        if m:
            idx = int(m.group(1))
            ssid = m.group(2).strip()
            rssi = int(m.group(3))
            security = m.group(4).strip()
            channel = int(m.group(5))
            self.networks[idx] = {
                "ssid": ssid,
                "rssi": rssi,
                "security": security,
                "channel": channel,
            }
            self._reload_network_table()

        # ¿Seleccionada?
        if RE_SELECTED.search(line):
            pass

        # ¿Pide contraseña?
        if RE_NEED_PASS.search(line):
            self.waiting_password = True
            self._update_buttons_state()

        # IPs de conexión
        m = RE_IP_LOCAL.search(line)
        if m:
            self.ip_local_var.set(m.group(1))
            self.connected = True
            self._update_buttons_state()

        m = RE_GATEWAY.search(line)
        if m:
            self.gateway_var.set(m.group(1))

        m = RE_SUBMASK.search(line)
        if m:
            self.mask_var.set(m.group(1))

        # Dispositivo activo
        m = RE_ACTIVE.search(line)
        if m:
            ip = m.group(1)
            # Evitar duplicados
            existing = set(self.ip_list.get(0, "end"))
            if ip not in existing:
                self.ip_list.insert("end", ip)

    def _reload_network_table(self):
        # Limpiar y recargar tabla
        for it in self.tree.get_children():
            self.tree.delete(it)
        for idx in sorted(self.networks):
            n = self.networks[idx]
            # Agregar emojis según el tipo de red
            security_icon = "🔒" if n["security"] == "Segura" else "🔓"
            # Colorear RSSI según intensidad
            rssi_display = f"{n['rssi']} dBm"
            values = (idx, n["ssid"], rssi_display, f"{security_icon} {n['security']}", n["channel"])
            self.tree.insert("", "end", iid=str(idx), values=values)
        self._update_buttons_state()

    def _toggle_pass(self):
        self.pass_entry.config(show="" if self.show_pass.get() else "•")

    def _get_selected_index(self):
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except Exception:
            return None

    def _send_selected_index(self):
        if not self.ser:
            return
        idx = self._get_selected_index()
        if idx is None:
            messagebox.showinfo("Selección", "Selecciona una red de la tabla.")
            return

        if self.conn_mode.get():
            # Protocolo CONN: CONN:<SSID>,<PASSWORD>
            ssid = self.networks.get(idx, {}).get("ssid", "")
            pwd = self.pass_entry.get()
            cmd = f"CONN:{ssid},{pwd}\n"
        else:
            # Solo enviar el número (como pide tu sketch)
            cmd = f"{idx}\n"

        try:
            self.ser.write(cmd.encode("utf-8"))
            if self.conn_mode.get():
                self.waiting_password = False
            self._append_log(f"📤 >>> {cmd}")
        except Exception as e:
            messagebox.showerror("Serial", f"Error enviando datos:\n{e}")

        # Habilitar botón de contraseña si no usamos CONN y la red es segura
        self._update_buttons_state()

    def _send_password_or_conn(self):
        if not self.ser:
            return
        if self.conn_mode.get():
            # Alternativa: conectar en un solo paso con CONN usando la red seleccionada
            idx = self._get_selected_index()
            if idx is None:
                messagebox.showinfo("Selección", "Selecciona una red de la tabla.")
                return
            ssid = self.networks.get(idx, {}).get("ssid", "")
            pwd = self.pass_entry.get()
            cmd = f"CONN:{ssid},{pwd}\n"
        else:
            # Flujo nativo del sketch: ya se envió el número; ahora solo la contraseña
            pwd = self.pass_entry.get()
            if not self.waiting_password and not pwd:
                messagebox.showinfo("Contraseña", "El ESP32 aún no ha solicitado la contraseña.")
                return
            cmd = pwd + "\n"

        try:
            self.ser.write(cmd.encode("utf-8"))
            self._append_log(f"🔑 >>> {cmd if self.conn_mode.get() else '***\\n'}")
        except Exception as e:
            messagebox.showerror("Serial", f"Error enviando datos:\n{e}")

    def _update_buttons_state(self):
        has_serial = self.ser is not None
        has_sel = self._get_selected_index() is not None
        self.send_idx_btn.config(state=("normal" if has_serial and has_sel else "disabled"))

        # Si usamos protocolo CONN, el botón de contraseña se usa también (envía todo)
        if self.conn_mode.get():
            self.send_pass_btn.config(state=("normal" if has_serial and has_sel else "disabled"))
        else:
            # Flujo por pasos: contraseña solo cuando el ESP32 la pida
            self.send_pass_btn.config(state=("normal" if has_serial and self.waiting_password else "disabled"))

    def _append_log(self, text):
        self.log.insert("end", text)
        self.log.see("end")

    def _copy_ips(self):
        ips = "\n".join(self.ip_list.get(0, "end"))
        if ips:
            self.clipboard_clear()
            self.clipboard_append(ips)
            messagebox.showinfo("📋 Copiado", "IPs copiadas al portapapeles.")
        else:
            messagebox.showinfo("📋 Sin datos", "No hay IPs para copiar.")

    def _clear_ips(self):
        self.ip_list.delete(0, "end")


if __name__ == "__main__":
    app = ESP32WiFiGUI()
    app.mainloop()