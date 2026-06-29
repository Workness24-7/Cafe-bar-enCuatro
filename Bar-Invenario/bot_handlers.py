import logging
import os
import psycopg2
from psycopg2.extras import DictCursor
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

log = logging.getLogger(__name__)

# Definición limpia de todos los estados requeridos
(
    SELECT_ROLE, ADMIN_MENU, EMPLOYEE_MENU, VENTA_CLIENTE, VENTA_PRODUCTO,
    VENTA_PRODUCTO_SELECTION, VENTA_PRODUCTO_NEW_NAME, VENTA_PRODUCTO_NEW_CANTIDAD,
    VENTA_PRODUCTO_NEW_PRECIO, VENTA_MULTIPLE_INPUT, VENTA_CANTIDAD, VENTA_PRECIO,
    VENTA_ESTADO, VENTA_PAGO_METODO, VENTA_ABONO, ADMIN_GESTION_PROD,
    ADMIN_GESTION_PROD_NOMBRE, ADMIN_GESTION_PROD_CANT, ADMIN_GESTION_PROD_BASE,
    ADMIN_GESTION_PROD_MIN, ADMIN_ELIMINAR_PROD, ADMIN_ELIMINAR_STOCK_SEL,
    ADMIN_ELIMINAR_STOCK_CANT, ADMIN_AGREGAR_STOCK_SEL, ADMIN_AGREGAR_STOCK_CANT,
    REPOPT_TIPO, REPOPT_ANO, REPOPT_MES, REPOPT_SEMANAS, ADMIN_REGISTRO_PAGOS,
    ADMIN_REGISTRO_PAGOS_CAT, VENTA_AGREGAR_OTRO, VENTA_PAGO_ESTADO,
    VENTA_PAGO_ABONO, ADMIN_REGISTRO_PAGOS_DESC, REGISTRO_GASTO_TIPO, REGISTRO_GASTO_MONTO
) = range(37)

def get_db_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"), cursor_factory=DictCursor)

def _mk_keyboard(options):
    return ReplyKeyboardMarkup([[KeyboardButton(opt)] for opt in options], resize_keyboard=True, one_time_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("👋 ¡Bienvenido a *Cafe Bar en Cuatro*!\n\nPara continuar, por favor ingresa tu código de acceso único (Empleada o Patrón):", parse_mode="Markdown")
    return SELECT_ROLE

async def select_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = (update.message.text or "").strip()
    user = update.effective_user
    
    # Intenta leer tus claves desde Railway, si no existen usa las de respaldo
    CLAVE_ADMIN = os.getenv("CLAVE_ACCESO_ADMIN", "AdminBar2026")
    CLAVE_EMPLEADO = os.getenv("CLAVE_ACCESO_EMPLEADO", "StaffBar2026")
    
    if code == CLAVE_ADMIN:
        rol = "AlejoAbella"
    elif code == CLAVE_EMPLEADO:
        rol = "Laura"
    else:
        await update.message.reply_text("❌ Código incorrecto. Intenta nuevamente:")
        return SELECT_ROLE
        
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM usuarios WHERE id_telegram = %s", (user.id,))
        cur.execute("INSERT INTO usuarios (id_telegram, nombre, rol) VALUES (%s, %s, %s)", (user.id, user.first_name, rol))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"✅ Registro exitoso como *{rol.upper()}*.", parse_mode="Markdown")
    await _show_main_menu(update, context, rol)
    return ADMIN_MENU if rol == "admin" else EMPLOYEE_MENU

async def _show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, rol: str) -> None:
    if rol == "admin":
        options = ["📦 Ver tabla de inventario", "🛠️ Gestionar productos", "💰 Control de deudores general", "💸 Registrar pagos administrativos", "🗂️ Módulo de reportes", "🔙 Salir"]
    else:
        options = ["🛒 Registrar pedido/venta", "💳 Ver cuentas por cobrar", "📥 Registrar gasto recurrente", "📦 Consultar inventario", "🔙 Salir"]
    await update.message.reply_text(f"🛠️ *Menú {rol.upper()}*", reply_markup=_mk_keyboard(options), parse_mode="Markdown")

async def employee_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = (update.message.text or "").strip()
    if choice == "🔙 Volver":
        await _show_main_menu(update, context, "empleado")
        return EMPLOYEE_MENU
    if choice == "📦 Consultar inventario":
        await update.message.reply_text("📦 Consultando inventario...")
        return EMPLOYEE_MENU
    return EMPLOYEE_MENU
