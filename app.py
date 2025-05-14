import gi
import asyncio
import websockets
import threading
import random
import string
import logging
import socket
import pyperclip
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
import uvicorn
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf
from uuid import uuid4
import io
import json
import qrcode
from PIL import Image


# --- Global variables ---
connected_clients = {}
last_clipboard = ""

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- FastAPI app ---
fastapi_app = FastAPI()

@fastapi_app.websocket("/ws/{device_id}")
async def websocket_endpoint(websocket: WebSocket, device_id: str):
    global connected_clients, last_clipboard
    
    # Check if device is already connected
    if device_id in connected_clients:
        logger.warning(f"Device {device_id} already connected. Closing previous connection.")
        await connected_clients[device_id].close()
    
    await websocket.accept()
    connected_clients[device_id] = websocket
    logger.info(f"Device {device_id} connected via WebSocket")
    
    # Update UI
    if ClipboardSyncApp.instance():
        GLib.idle_add(
            ClipboardSyncApp.instance().update_status_label, 
            f"Status: {device_id[:8]}... Connected"
        )

    try:
        while True:
            data = await websocket.receive_text()
            logger.debug(f"Received data from {device_id}: {data[:100]}...")
            
            try:
                message = json.loads(data)
                
                # Handle pairing request
                if message.get('type') == 'pairing_request':
                    logger.info(f"Pairing request from {device_id}")
                    await websocket.send_json({
                        "type": "pairing_response",
                        "success": True,
                        "message": "Pairing successful"
                    })
                    continue
                
                # Handle clipboard update
                if message.get('type') == 'clipboard_update' and 'text' in message:
                    content = message['text']
                    if content and content != last_clipboard:
                        pyperclip.copy(content)
                        last_clipboard = content
                        logger.info(f"Received clipboard update from {device_id}")
                        
                        # Broadcast to other connected devices
                        for client_id, client_ws in connected_clients.items():
                            if client_id != device_id and client_ws.application_state == WebSocketState.CONNECTED:
                                try:
                                    await client_ws.send_json({
                                        "type": "clipboard_update",
                                        "text": content,
                                        "source": device_id
                                    })
                                except Exception as e:
                                    logger.error(f"Error broadcasting to {client_id}: {e}")
                    
                    await websocket.send_json({
                        "status": "success",
                        "message": "Clipboard updated"
                    })
                    continue
                
                # Fallback for plain text
                if 'text' in message:
                    content = message['text']
                    if content and content != last_clipboard:
                        pyperclip.copy(content)
                        last_clipboard = content
                        logger.info(f"Received text from {device_id}")
                
            except json.JSONDecodeError:
                # Handle non-JSON messages
                if data and data != last_clipboard:
                    pyperclip.copy(data)
                    last_clipboard = data
                    logger.info(f"Received plain text from {device_id}")
            
    except WebSocketDisconnect as e:
        logger.warning(f"Device {device_id} disconnected: {e}")
    except Exception as e:
        logger.error(f"Error with device {device_id}: {e}")
    finally:
        connected_clients.pop(device_id, None)
        if ClipboardSyncApp.instance():
            GLib.idle_add(
                ClipboardSyncApp.instance().update_status_label,
                f"Status: {device_id[:8]}... Disconnected"
            )

# --- Clipboard monitor ---
def start_clipboard_monitor():
    async def monitor():
        global last_clipboard
        while True:
            try:
                content = pyperclip.paste()
                if content and content != last_clipboard:
                    last_clipboard = content
                    
                    # Send to all connected clients
                    for device_id, ws in connected_clients.items():
                        if ws.application_state == WebSocketState.CONNECTED:
                            try:
                                await ws.send_json({
                                    "type": "clipboard_update",
                                    "text": content,
                                    "source": "desktop"
                                })
                                logger.info(f"Sent clipboard update to {device_id}")
                            except Exception as e:
                                logger.error(f"Error sending to {device_id}: {e}")
                                connected_clients.pop(device_id, None)
            
            except Exception as e:
                logger.error(f"Clipboard monitor error: {e}")
            
            await asyncio.sleep(1)

    threading.Thread(target=lambda: asyncio.run(monitor()), daemon=True).start()

# --- GTK Application ---
class ClipboardSyncApp(Gtk.Window):
    _instance = None

    def __init__(self):
        super().__init__(title="Clipboard Sync")
        ClipboardSyncApp._instance = self

        self.set_default_size(600, 400)
        self.device_id = str(uuid4())
        self.pairing_code = self.generate_pairing_code()
        self.hostname = socket.gethostname()
        self.ip_address = self.get_ip_address()

        self.build_ui()
        self.apply_css()
        self.connect("destroy", self.on_destroy)

    @classmethod
    def instance(cls):
        return cls._instance

    def generate_pairing_code(self):
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

    def build_ui(self):
        header_bar = Gtk.HeaderBar(title="Clipboard Sync")
        header_bar.set_show_close_button(True)
        self.set_titlebar(header_bar)

        self.status_label = Gtk.Label(label="Status: Waiting for connection...")
        header_bar.pack_start(self.status_label)

        refresh_button = Gtk.Button(label="Refresh")
        refresh_button.connect("clicked", self.on_refresh_clicked)
        header_bar.pack_end(refresh_button)

        notebook = Gtk.Notebook()
        self.add(notebook)

        # Pairing Tab
        pairing_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        pairing_box.set_margin_top(20)
        pairing_box.set_margin_bottom(20)
        pairing_box.set_margin_start(20)
        pairing_box.set_margin_end(20)

        # Instructions
        instructions_label = Gtk.Label(label="Scan the QR code or enter the pairing code in your mobile app to connect.")
        pairing_box.pack_start(instructions_label, False, False, 0)

        # QR Code
        uri = f"ws://{self.ip_address}:8000/ws/{self.device_id}?code={self.pairing_code}"
        qr = qrcode.make(uri)
        img_bytes = io.BytesIO()
        qr.save(img_bytes, format='PNG')
        img_bytes.seek(0)

        loader = GdkPixbuf.PixbufLoader.new_with_type('png')
        loader.write(img_bytes.read())
        loader.close()
        qr_pixbuf = loader.get_pixbuf()

        if qr_pixbuf.get_width() > 300 or qr_pixbuf.get_height() > 300:
            qr_pixbuf = qr_pixbuf.scale_simple(300, 300, GdkPixbuf.InterpType.BILINEAR)

        qr_image_widget = Gtk.Image.new_from_pixbuf(qr_pixbuf)
        pairing_box.pack_start(qr_image_widget, False, False, 10)

        # Pairing Code
        pairing_code_frame = Gtk.Frame(label="Pairing Code")
        pairing_code_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        pairing_code_frame.add(pairing_code_box)
        
        pairing_code_label = Gtk.Label(label=self.pairing_code)
        pairing_code_label.set_name("pairing_code_label")
        pairing_code_box.pack_start(pairing_code_label, False, False, 5)
        
        pairing_box.pack_start(pairing_code_frame, False, False, 10)

        # Device Info
        device_info_frame = Gtk.Frame(label="Device Information")
        device_info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        device_info_frame.add(device_info_box)
        
        device_id_label = Gtk.Label(label=f"Device ID: {self.device_id}")
        hostname_label = Gtk.Label(label=f"Hostname: {self.hostname}")
        ip_label = Gtk.Label(label=f"IP Address: {self.ip_address}")
        
        device_info_box.pack_start(device_id_label, False, False, 2)
        device_info_box.pack_start(hostname_label, False, False, 2)
        device_info_box.pack_start(ip_label, False, False, 2)
        
        pairing_box.pack_start(device_info_frame, False, False, 10)

        notebook.append_page(pairing_box, Gtk.Label(label="Pairing"))

    def apply_css(self):
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            #pairing_code_label {
                font-family: Monospace;
                font-size: 24px;
                font-weight: bold;
                color: #2c3e50;
            }
            frame {
                margin: 10px;
            }
        """)
        screen = Gdk.Screen.get_default()
        style_context = Gtk.StyleContext()
        style_context.add_provider_for_screen(screen, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def get_ip_address(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip_address = s.getsockname()[0]
            s.close()
            return ip_address
        except Exception as e:
            logger.error(f"Error getting IP address: {e}")
            return socket.gethostbyname(socket.gethostname())

    def update_status_label(self, status):
        self.status_label.set_text(status)

    def on_refresh_clicked(self, button):
        self.pairing_code = self.generate_pairing_code()
        logger.info(f"Pairing code refreshed: {self.pairing_code}")
        for child in self.get_children():
            self.remove(child)
        self.build_ui()
        self.show_all()

    def on_destroy(self, *args):
        Gtk.main_quit()

# --- Run server & app ---
def run_fastapi():
    uvicorn.run(
        fastapi_app, 
        host="0.0.0.0", 
        port=8000,
        log_level="info",
        ws_ping_interval=20,
        ws_ping_timeout=30
    )

def main():
    # Start FastAPI server in background
    threading.Thread(target=run_fastapi, daemon=True).start()
    start_clipboard_monitor()

    # Start GTK App
    app = ClipboardSyncApp()
    app.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
    
    