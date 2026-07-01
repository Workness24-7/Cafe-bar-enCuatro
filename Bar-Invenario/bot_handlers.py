# bot_handlers.py
import logging
import re
import sqlite3
from datetime import datetime
import datetime
from typing import List

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from db import (
    get_user,
    create_user,
    delete_user,
    add_product,
    remove_product,
    list_inventory,
    get_product,
    record_sale,
    query_pending_payments,
    mark_payment_full,
    register_partial_payment,
    record_expense,
    update_stock,
    _fmt_money,
)
from reports import generate_text_report, generate_pdf_report, SPANISH_MONTHS
from config import (
    CLAVE_ACCESO_ADMIN,
    CLAVE_ACCESO_EMPLEADO,
    NOMBRE_NEGOCIO,
    SIGNO_MONEDA,
    FORMATO_MILES,
    DB_PATH,
)

log = logging.getLogger(__name__)

# ----------------------------------------------------------------------
#  Conversation state constants – must match the order used in main.py
# ----------------------------------------------------------------------
# Conversation state constants – generated dynamically to avoid mismatches
_STATE_NAMES = [
    "SELECT_ROLE",
    "ADMIN_MENU",
    "EMPLOYEE_MENU",
    "VENTA_CLIENTE",
    "VENTA_PRODUCTO",
    "VENTA_PRODUCTO_SELECTION",
    "VENTA_PRODUCTO_NEW_NAME",
    "VENTA_PRODUCTO_NEW_CANTIDAD",
    "VENTA_PRODUCTO_NEW_PRECIO",
    "VENTA_MULTIPLE_INPUT",
    "VENTA_CANTIDAD",
    "VENTA_PRECIO",
    "VENTA_ESTADO",
    "VENTA_PAGO_METODO",
        "VENTA_ABONO",
    "ADMIN_GESTION_PROD",
    "ADMIN_GESTION_PROD_NOMBRE",
    "ADMIN_GESTION_PROD_CANT",
    "ADMIN_GESTION_PROD_BASE",
    "ADMIN_GESTION_PROD_MIN",
    "ADMIN_ELIMINAR_PROD",
    "ADMIN_ELIMINAR_STOCK_SEL",
    "ADMIN_ELIMINAR_STOCK_CANT",
    "ADMIN_AGREGAR_STOCK_SEL",
    "ADMIN_AGREGAR_STOCK_CANT",
    "REPOPT_TIPO",
    "REPOPT_ANO",
    "REPOPT_MES",
    "REPOPT_RANGO",
    "ADMIN_REGISTRO_PAGOS",
    "ADMIN_REGISTRO_PAGOS_CAT",
    "VENTA_AGREGAR_OTRO",
    "VENTA_PAGO_ESTADO",
    "VENTA_PAGO_ABONO",
    "ADMIN_REGISTRO_PAGOS_CAT",
    "ADMIN_REGISTRO_PAGOS_DESC",
    ]

# Export each name as a module‑level constant with a unique integer value
for _idx, _name in enumerate(_STATE_NAMES):
    globals()[_name] = _idx
# Clean up temporary helpers
del _idx, _name, _STATE_NAMES
# New state for expense registration flow (separate from report type)
REGISTRO_GASTO_TIPO = max([v for v in globals().values() if isinstance(v, int)]) + 1
REGISTRO_GASTO_MONTO = REGISTRO_GASTO_TIPO + 1

# ----------------------------------------------------------------------
#  Helper to build a simple keyboard from a list of strings
# ----------------------------------------------------------------------
def _mk_keyboard(options: List[str]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(opt)] for opt in options],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

# ----------------------------------------------------------------------
#  Money formatter for user‑visible messages
# ----------------------------------------------------------------------
def _fmt_money(value: float) -> str:
    if FORMATO_MILES:
        return f"{SIGNO_MONEDA}{int(value):,}".replace(",", ".")
    return f"{SIGNO_MONEDA}{value:.2f}"

# ----------------------------------------------------------------------
#  /start – entry point
# ----------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Always ask for the access code to allow switching roles
    # (previously we auto‑login if the user already existed)
    await update.message.reply_text(
        f"👋 ¡Bienvenido a {NOMBRE_NEGOCIO}!\n"
        "Para continuar, ingresa el código de acceso que te haya sido entregado (Empleada o Patron):",
        parse_mode="Markdown",
    )
    return SELECT_ROLE

async def select_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Always process the access code, allowing role switching
    code = (update.message.text or "").strip()
    user = update.effective_user
    if code == CLAVE_ACCESO_ADMIN:
        rol = "admin"
    elif code == CLAVE_ACCESO_EMPLEADO:
        rol = "empleado"
    else:
        await update.message.reply_text(
            "❌ Código incorrecto. Intenta nuevamente o contacta al administrador."
        )
        return SELECT_ROLE

    # Registro/actualización del usuario en PostgreSQL
    nombre = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Sin nombre"
    create_user(user.id, nombre, rol)
    # Guardamos el rol en la sesión (sobrescribe cualquier rol previo)
    context.user_data["role"] = rol
    await update.message.reply_text(f"✅ Registro exitoso como *{rol}*.", parse_mode="Markdown")
    await _show_main_menu(update, context, rol)
    return ADMIN_MENU if rol == "admin" else EMPLOYEE_MENU

async def _show_main_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, rol: str
) -> None:
    if rol == "admin":
        options = [
            "📦 Ver tabla de inventario",
            "🛠️ Gestionar productos",
            "💰 Control de deudores general",
            "💸 Registrar pagos administrativos",
            "🗂️ Módulo de reportes",
            "🔙 Salir",
        ]
        await update.effective_message.reply_text(
            "🛠️ *Menú Administrador*",
            reply_markup=_mk_keyboard(options),
            parse_mode="Markdown",
        )
    else:
        options = [
            "🛒 Registrar pedido/venta",
            "💳 Ver cuentas por cobrar",
            "📥 Registrar gasto recurrente",
            "📦 Consultar inventario",
            "🔙 Salir",
        ]
        await update.effective_message.reply_text(
            "👤 *Menú Empleado*",
            reply_markup=_mk_keyboard(options),
            parse_mode="Markdown",
        )

# ----------------------------------------------------------------------
#  EMPLOYEE MENU dispatcher
# ----------------------------------------------------------------------
async def employee_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = (update.message.text or "").strip()
    # Volver al menú principal de empleado
    if choice == "🔙 Volver":
        await _show_main_menu(update, context, "empleado")
        return EMPLOYEE_MENU

    if choice == "🛒 Registrar pedido/venta":
        await update.message.reply_text("👤 *Nombre del cliente*:", parse_mode="Markdown")
        return VENTA_CLIENTE

    if choice == "💳 Ver cuentas por cobrar":
        pending = query_pending_payments()
        if not pending:
            await update.message.reply_text("✅ No hay cuentas pendientes.")
            return EMPLOYEE_MENU
        # Agrupar por cliente
        from collections import defaultdict
        grouped = defaultdict(list)
        for p in pending:
            grouped[p['cliente']].append(p)
        # Guardar agrupación para uso posterior
        context.user_data['cobro_grouped'] = dict(grouped)
        # Crear botones con nombres de clientes
        client_buttons = [
            InlineKeyboardButton(cliente, callback_data=f"cobro_cliente:{cliente}")
            for cliente in grouped.keys()
        ]
        # Añadir botón Volver
        client_buttons.append(InlineKeyboardButton("🔙 Volver", callback_data="cobro_volver"))
        keyboard = [client_buttons]
        await update.message.reply_text(
            "💳 Selecciona el cliente cuyas cuentas deseas gestionar:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return EMPLOYEE_MENU

    if choice == "📥 Registrar gasto recurrente":
        # Iniciar flujo de registro de gasto recurrente: pedir descripción y monto
        context.user_data["temp_expense"] = {"tipo": "operativo_bar"}
        await update.message.reply_text("🧾 *Descripción del gasto*:", parse_mode="Markdown")
        return REGISTRO_GASTO_TIPO

    if choice == "📦 Consultar inventario":
        inv = list_inventory()
        if not inv:
            await update.message.reply_text("🚫 Inventario vacío.")
        else:
            lines = ["*Inventario:*"]
            for i in inv:
                lines.append(
                    f"{i['nombre_producto']}: {i['cantidad']} uds "
                    f"({_fmt_money(i['precio_base'])} c/u)"
                )
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return EMPLOYEE_MENU

    if choice == "🔙 Salir":
        await update.message.reply_text(
            f"👋 ¡Bienvenido a {NOMBRE_NEGOCIO}!\n"
            "Para continuar, ingresa el código de acceso que te haya sido entregado (Empleada o Patron):",
            parse_mode="Markdown",
        )
        return SELECT_ROLE

    await update.message.reply_text("❓ Opción no reconocida.")
    return EMPLOYEE_MENU

# ----------------------------------------------------------------------
#  EMPLOYEE – venta flow handlers
# ----------------------------------------------------------------------
async def venta_cliente(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Guardar cliente y preparar lista de ítems
    context.user_data["venta_items"] = []
    context.user_data["venta"] = {"cliente": update.message.text.strip()}
    await update.message.reply_text("🛍️ *Ingresa los productos y cantidades (ej: 2 Poker, 1 Aguila)*:", parse_mode="Markdown")
    return VENTA_MULTIPLE_INPUT


async def venta_multiple_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Parsea la línea de productos como "3 Poker, 1 Aguila" y prepara la venta.
    Se asume que los productos existen; se usa el precio mínimo de venta como precio de venta.
    """
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("❌ No ingresaste nada. Intenta de nuevo.")
        return VENTA_MULTIPLE_INPUT
    # separar por comas
    parts = [p.strip() for p in re.split(r',\s*', text) if p.strip()]
    items = []
    for part in parts:
        m = re.match(r"^(\d+)\s+(.+)$", part)
        if not m:
            await update.message.reply_text("❌ Formato incorrecto. Usa: <cantidad> <producto>, ...")
            return VENTA_MULTIPLE_INPUT
        cant = int(m.group(1))
        nombre = m.group(2).strip()
        prod = get_product(nombre)
        if not prod:
            await update.message.reply_text(f"❌ Producto '{nombre}' no encontrado.")
            return VENTA_MULTIPLE_INPUT
        # usar precio mínimo como precio de venta
        precio = prod["precio_minimo_venta"]
        items.append({
            "producto": nombre,
            "cantidad": cant,
            "precio_vendido": precio,
            "es_nuevo": False,
        })
    # Guardar ítems
    context.user_data["venta_items"] = items
    # Calcular total
    total = sum(i["precio_vendido"] * i["cantidad"] for i in items)
    await update.message.reply_text(
        f"🧾 *Total de la venta:* {_fmt_money(total)}",
        parse_mode="Markdown",
    )
    # Preguntar método de pago
    await update.message.reply_text(
        "💳 ¿Cómo se realizará el pago?",
        reply_markup=_mk_keyboard(["DEBE", "PAGO", "PARCIAL"]),
    )
    return VENTA_PAGO_ESTADO

async def venta_producto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    nombre = update.message.text.strip()
    prod = get_product(nombre)
    if not prod:
        await update.message.reply_text("❌ Producto no encontrado. Intenta otro.")
        return VENTA_PRODUCTO
    context.user_data["venta"]["producto"] = nombre
    context.user_data["venta"]["producto_data"] = prod
    await update.message.reply_text("🔢 *Cantidad*:", parse_mode="Markdown")
    return VENTA_CANTIDAD

async def venta_cantidad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        cant = int(update.message.text.strip())
        if cant <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Ingresa un número entero positivo.")
        return VENTA_CANTIDAD
    # Get the last item being processed
    item = context.user_data["venta_items"][-1]
    if not item.get("es_nuevo"):
        prod = get_product(item["producto"])
        if not prod:
            await update.message.reply_text("❌ Producto no encontrado.")
            return VENTA_PRODUCTO_SELECTION
        if cant > prod["cantidad"]:
            await update.message.reply_text(
                f"⚠️ Stock insuficiente ({prod['cantidad']} disponible)."
            )
            return VENTA_CANTIDAD
    item["cantidad"] = cant
    await update.message.reply_text("💲 *Precio de venta* (por unidad):", parse_mode="Markdown")
    return VENTA_PRECIO

async def venta_precio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        precio = float(update.message.text.strip())
        if precio <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Ingresa un número válido mayor a 0.")
        return VENTA_PRECIO
    # Get the last item being processed
    item = context.user_data["venta_items"][-1]
    if not item.get("es_nuevo"):
        prod = get_product(item["producto"])
        if not prod:
            await update.message.reply_text("❌ Producto no encontrado.")
            return VENTA_PRODUCTO_SELECTION
        if precio < prod["precio_minimo_venta"]:
            await update.message.reply_text(
                f"❌ Precio menor al mínimo permitido ({_fmt_money(prod['precio_minimo_venta'])})."
            )
            return VENTA_PRECIO
    # Store price in the item
    item["precio_vendido"] = precio
    # Ask if user wants to add another product
    await update.message.reply_text(
        "✅ Ítem registrado. ¿Agregar otro producto?",
        reply_markup=_mk_keyboard(["Sí", "No"]),
    )
    return VENTA_AGREGAR_OTRO

async def venta_estado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    estado = (update.message.text or "").strip().upper()
    if estado not in ("DEBE", "PAGO", "PARCIAL"):
        await update.message.reply_text("❌ Elige DEBE, PAGO o PARCIAL.")
        return VENTA_ESTADO
    context.user_data["venta"]["estado"] = estado
    if estado == "PARCIAL":
        await update.message.reply_text("💵 *Monto abonado*:", parse_mode="Markdown")
        return VENTA_ABONO
    # else, finish registration
    await _finalizar_venta(update, context)
    return EMPLOYEE_MENU

async def venta_abono(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        abono = float(update.message.text.strip())
        if abono <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Ingresa un número válido mayor a 0.")
        return VENTA_ABONO
    # Manejar caso multi‑producto vs simple
    if context.user_data.get("venta_items"):
        # Guardar abono total para repartir proporcionalmente
        context.user_data["venta"]["abono_total"] = abono
        await _finalizar_venta_multiple(update, context)
    else:
        context.user_data["venta"]["abono"] = abono
        await _finalizar_venta(update, context)
    return EMPLOYEE_MENU

# ----------------------------------------------------------------------
#  New employee flow helpers for multi‑product sales
# ----------------------------------------------------------------------
async def venta_producto_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # User selected a product from the keyboard (or "Nuevo producto")
    choice = update.message.text.strip()
    if choice == "Nuevo producto":
        await update.message.reply_text("🆕 *Nombre del nuevo producto*:", parse_mode="Markdown")
        return VENTA_PRODUCTO_NEW_NAME
    # Existing product → store and ask for quantity
    context.user_data.setdefault("venta_items", []).append({
        "producto": choice,
        "es_nuevo": False,
    })
    await update.message.reply_text("🔢 *Cantidad*:", parse_mode="Markdown")
    return VENTA_CANTIDAD

async def venta_producto_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_product_name"] = update.message.text.strip()
    await update.message.reply_text("🔢 *Cantidad a vender*:", parse_mode="Markdown")
    return VENTA_PRODUCTO_NEW_CANTIDAD

async def venta_producto_new_cantidad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        cant = int(update.message.text.strip())
        if cant <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Ingresa un número entero positivo.")
        return VENTA_PRODUCTO_NEW_CANTIDAD
    context.user_data["new_product_cantidad"] = cant
    await update.message.reply_text("💲 *Precio de venta (y precio base) *:", parse_mode="Markdown")
    return VENTA_PRODUCTO_NEW_PRECIO

async def venta_producto_new_precio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        precio = float(update.message.text.strip())
        if precio <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Ingresa un número válido.")
        return VENTA_PRODUCTO_NEW_PRECIO
    # Save new product as an item (will be created on finalization)
    context.user_data.setdefault("venta_items", []).append({
        "producto": context.user_data["new_product_name"],
        "cantidad": context.user_data["new_product_cantidad"],
        "precio_vendido": precio,
        "es_nuevo": True,
    })
    await update.message.reply_text("✅ Ítem registrado. ¿Agregar otro producto?", reply_markup=_mk_keyboard(["Sí", "No"]))
    return VENTA_AGREGAR_OTRO

async def venta_agregar_otro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    resp = (update.message.text or "").strip().lower()
    if resp in ("sí", "si", "s", "yes", "y"):
        # Show product list again
        products = [p["nombre_producto"] for p in list_inventory()]
        options = products + ["Nuevo producto"]
        await update.message.reply_text("📦 *Elige un producto*:", reply_markup=_mk_keyboard(options), parse_mode="Markdown")
        return VENTA_PRODUCTO_SELECTION
    # No more items – compute total and ask for payment method
    items = context.user_data.get("venta_items", [])
    total = sum(item["precio_vendido"] * item["cantidad"] for item in items)
    await update.message.reply_text(
        f"🧾 *Total de la venta:* {_fmt_money(total)}",
        parse_mode="Markdown",
    )
    # Ask how the payment will be handled
    await update.message.reply_text(
        "💳 ¿Cómo se realizará el pago?",
        reply_markup=_mk_keyboard(["DEBE", "PAGO", "PARCIAL"]),
    )
    return VENTA_PAGO_ESTADO

async def _finalizar_venta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Legacy single-item finalizer (kept for compatibility)
    v = context.user_data.get("venta")
    if not v:
        return
    try:
        record_sale(
            cliente=v["cliente"],
            producto=v["producto"],
            cantidad=v["cantidad"],
            precio_vendido=v["precio_vendido"],
            estado_pago=v["estado"],
            metodo_pago=v.get("metodo_pago", "Desconocido"),
            abono=v.get("abono", 0.0),
        )
        await update.message.reply_text("✅ Venta Registrada.")
        await _show_main_menu(update, context, "empleado")
    except Exception as e:
        log.exception("Error al registrar venta")
        await update.message.reply_text(f"❌ Error al registrar la venta: {e}")
    finally:
        context.user_data.pop("venta", None)

# ----------------------------------------------------------------------
#  Multi‑producto sale finalizer
# ----------------------------------------------------------------------
async def _finalizar_venta_multiple(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    venta = context.user_data.get("venta", {})
    items = context.user_data.get("venta_items", [])
    estado = venta.get("estado", "PAGO")
    abono_total = venta.get("abono_total", 0.0)
    total = sum(item["precio_vendido"] * item["cantidad"] for item in items)
    for item in items:
        # crear producto si es nuevo
        if item.get("es_nuevo"):
            add_product(
                nombre_producto=item["producto"],
                cantidad=item["cantidad"],
                precio_base=item["precio_vendido"],
                precio_minimo_venta=item["precio_vendido"],
            )
        # calcular abono por ítem si corresponde
        abono_item = 0.0
        if estado == "PARCIAL" and total > 0:
            # proporción del subtotal del ítem respecto al total
            subtotal = item["precio_vendido"] * item["cantidad"]
            abono_item = round(abono_total * subtotal / total, 2)
        record_sale(
            cliente=venta.get("cliente"),
            producto=item["producto"],
            cantidad=item["cantidad"],
            precio_vendido=item["precio_vendido"],
            estado_pago=estado,
            metodo_pago=context.user_data.get("venta", {}).get("metodo_pago", "Desconocido"),
            abono=abono_item,
        )
    await update.message.reply_text("✅ Venta Registrada.")
    await _show_main_menu(update, context, "empleado")
        # limpiar datos temporales
    context.user_data.pop("venta", None)
    context.user_data.pop("venta_items", None)

# ----------------------------------------------------------------------
#  EMPLOYEE – registrar gasto (re‑using REPOPT_TIPO state for simplicity)
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
#  EMPLOYEE – manejo del pago del pedido múltiple
# ----------------------------------------------------------------------
async def venta_pago_estado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Preguntar el estado del pago (DEBE, PAGO, PARCIAL) y actuar en consecuencia.
    Si es DEBE, finaliza la venta sin pedir método de pago.
    En caso de PAGO o PARCIAL, solicita el método de pago.
    """
    estado = (update.message.text or "").strip().upper()
    if estado not in ("DEBE", "PAGO", "PARCIAL"):
        await update.message.reply_text("❌ Elige DEBE, PAGO o PARCIAL.")
        return VENTA_PAGO_ESTADO
    # Guardar el estado seleccionado
    context.user_data.setdefault("venta", {})["estado"] = estado
    if estado == "DEBE":
        # Finalizar venta sin preguntar método de pago
        if context.user_data.get("venta_items"):
            await _finalizar_venta_multiple(update, context)
        else:
            await _finalizar_venta(update, context)
        return EMPLOYEE_MENU
    # Para PAGO o PARCIAL, preguntar método de pago
    await update.message.reply_text(
        "💳 *Selecciona método de pago*:",
        reply_markup=_mk_keyboard(["Transferencia", "Efectivo"]),
        parse_mode="Markdown",
    )
    return VENTA_PAGO_METODO

async def venta_pago_metodo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Captura el método de pago seleccionado por el empleado y continúa con la venta.
    El método se guarda en ``context.user_data["venta"]["metodo_pago"]`` y luego se delega a la rutina
    de finalización correspondiente.
    """
    metodo = (update.message.text or "").strip()
    if metodo not in ("Transferencia", "Efectivo"):
        await update.message.reply_text("❌ Selecciona Transferencia o Efectivo.")
        return VENTA_PAGO_METODO
    # Guardar método
    context.user_data.setdefault("venta", {})["metodo_pago"] = metodo
    # Continuar según flujo (múltiple o simple)
    if context.user_data.get("venta_items"):
        if context.user_data["venta"].get("estado") == "PARCIAL":
            await update.message.reply_text("💵 *Monto abonado*:", parse_mode="Markdown")
            return VENTA_ABONO
        await _finalizar_venta_multiple(update, context)
        return EMPLOYEE_MENU
    await _finalizar_venta(update, context)
    return EMPLOYEE_MENU

async def venta_pago_metodo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Captura el método de pago seleccionado por el empleado y continúa con la venta.
    El método se guarda en ``context.user_data["venta"]["metodo_pago"]`` y luego se delega
    a la rutina de finalización correspondiente.
    """
    metodo = (update.message.text or "").strip()
    if metodo not in ("Transferencia", "Efectivo"):
        await update.message.reply_text("❌ Selecciona Transferencia o Efectivo.")
        return VENTA_PAGO_METODO
    # Guardar método
    context.user_data.setdefault("venta", {})["metodo_pago"] = metodo
    # Continuar según flujo (múltiple o simple)
    if context.user_data.get("venta_items"):
        if context.user_data["venta"].get("estado") == "PARCIAL":
            await update.message.reply_text("💵 *Monto abonado*:", parse_mode="Markdown")
            return VENTA_ABONO
        await _finalizar_venta_multiple(update, context)
        return EMPLOYEE_MENU
    await _finalizar_venta(update, context)
    return EMPLOYEE_MENU

async def venta_pago_abono(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        abono_total = float(update.message.text.strip())
        if abono_total <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Ingresa un número válido mayor a 0.")
        return VENTA_PAGO_ABONO
    context.user_data["venta"]["abono_total"] = abono_total
    await _finalizar_venta_multiple(update, context)
    return EMPLOYEE_MENU

# ----------------------------------------------------------------------
#  EMPLOYEE – registrar gasto (re‑using REPOPT_TIPO state for simplicity)
# ----------------------------------------------------------------------
async def registrar_gasto_tipo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Ensure temp_expense exists (fallback for unexpected entry)
    if "temp_expense" not in context.user_data:
        context.user_data["temp_expense"] = {"tipo": "operativo_bar"}
    # This handler receives the expense description from the employee
    desc = (update.message.text or "").strip()
    if not desc:
        await update.message.reply_text("❌ Ingresa una descripción del gasto.")
        return REGISTRO_GASTO_TIPO
    # Store description and keep the default type (operativo_bar) set previously
    context.user_data["temp_expense"]["descripcion"] = desc
    await update.message.reply_text("💰 *Monto*:", parse_mode="Markdown")
    return REGISTRO_GASTO_MONTO

async def registrar_gasto_descripcion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Ensure temp_expense exists (fallback)
    if "temp_expense" not in context.user_data:
        context.user_data["temp_expense"] = {"tipo": "operativo_bar"}
    tipo = (update.message.text or "").strip()
    if tipo not in ("operativo_bar", "nomina", "servicios", "externo"):
        await update.message.reply_text("❌ Selecciona un tipo válido.")
        return ADMIN_MENU
    context.user_data["temp_expense"]["tipo"] = tipo
    await update.message.reply_text("🧾 *Descripción*:", parse_mode="Markdown")
    return ADMIN_MENU

async def registrar_gasto_monto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Ensure temp_expense exists (fallback)
    if "temp_expense" not in context.user_data:
        context.user_data["temp_expense"] = {"tipo": "operativo_bar"}
    # This handler receives the amount of the expense
    try:
        monto = float(update.message.text.strip())
        if monto <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Ingresa un monto válido.")
        return REGISTRO_GASTO_MONTO
    exp = context.user_data["temp_expense"]
    try:
        record_expense(exp["tipo"], exp["descripcion"], monto)
        await update.message.reply_text("✅ Gasto registrado.")
        await _show_main_menu(update, context, "empleado")
    except Exception as e:
        log.exception("Error al registrar gasto")
        await update.message.reply_text(f"❌ Error: {e}")
    finally:
        context.user_data.pop("temp_expense", None)
    return EMPLOYEE_MENU

# ----------------------------------------------------------------------
#  ADMIN MENU dispatcher
# ----------------------------------------------------------------------
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Asegurarnos de que el usuario sigue autenticado como admin
    if not context.user_data.get("role"):
        await update.message.reply_text("⚠️ No estás autenticado. Usa /start para iniciar sesión.")
        return SELECT_ROLE
    choice = (update.message.text or "").strip()
    # Volver al menú principal de administrador
    if choice == "🔙 Volver":
        await _show_main_menu(update, context, "admin")
        return ADMIN_MENU

    if "inventario" in choice.lower():
        # Mostrar inventario o indicar que está vacío
        inv = list_inventory()
        if not inv:
            await update.message.reply_text("🚫 Inventario vacío.", parse_mode="Markdown")
        else:
            # Formato: "inventario   3 Poker $ 4000 (c/u) --> $ 12000"
            lines = []
            for i in inv:
                line = f"inventario   {i['cantidad']} {i['nombre_producto']} {_fmt_money(i['precio_base'])} (c/u) --> {_fmt_money(i['valor_total_stock'])}"
                lines.append(line)
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        # No llamamos a _show_main_menu aquí; permanecemos en ADMIN_MENU
        return ADMIN_MENU

    if choice == "🛠️ Gestionar productos":
        await update.message.reply_text(
            "¿Qué deseas hacer?",
            reply_markup=_mk_keyboard(["Agregar producto", "Agregar stock", "Eliminar stock", "Eliminar producto", "🔙 Volver"]),
        )
        return ADMIN_GESTION_PROD

    if "deudores" in choice.lower():
        log.debug(f"ADMIN_MENU choice received: {choice!r}")
        try:
            pending = query_pending_payments()
            if not pending:
                await update.message.reply_text("✅ No hay deudores.")
            else:
                # Aggregate amounts per cliente y producto
                aggregation = {}
                total_deuda = 0.0
                for p in pending:
                    cliente = p.get('cliente', 'Desconocido')
                    producto = p.get('producto', 'Desconocido')
                    cantidad = p.get('cantidad', 0)
                    amount = p.get('saldo_pendiente')
                    if amount is None:
                        amount = p.get('subtotal', 0)
                    key = (cliente, producto)
                    if key not in aggregation:
                        aggregation[key] = {"cantidad": cantidad, "monto": amount}
                    else:
                        aggregation[key]["cantidad"] += cantidad
                        aggregation[key]["monto"] += amount
                    total_deuda += amount
                lines = ["*Deudores:*"]
                for (cliente, producto), data in aggregation.items():
                    lines.append(f"{cliente} - {data['cantidad']} - {producto} - {_fmt_money(data['monto'])}")
                lines.append(f"*Total a cobrar:* {_fmt_money(total_deuda)}")
                await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        except Exception as e:
            if isinstance(e, sqlite3.OperationalError) and "database is locked" in str(e):
                await update.message.reply_text(
                    "⚠️ Base de datos ocupada. Intenta de nuevo en unos segundos."
                )
            else:
                log.exception("Error en Control de deudores general")
                await update.message.reply_text("❌ Ocurrió un error al obtener los deudores.")
        return ADMIN_MENU

    if choice == "💸 Registrar pagos administrativos":
        # Ask for category first
        await update.message.reply_text(
            "💰 *Selecciona una categoría de pago administrativo*:",
            parse_mode="Markdown",
            reply_markup=_mk_keyboard(["Agua", "Luz", "Internet", "Otro", "🔙 Volver"]),
        )
        # Store placeholder for category
        context.user_data["admin_payment"] = {}
        return ADMIN_REGISTRO_PAGOS_CAT

    if choice == "🗂️ Módulo de reportes":
        await update.message.reply_text(
            "¿Qué formato deseas?",
            reply_markup=_mk_keyboard(["Texto", "PDF", "🔙 Volver"]),
        )
        return REPOPT_TIPO

    if choice == "🔙 Salir":
        await update.message.reply_text(
            f"👋 ¡Bienvenido a {NOMBRE_NEGOCIO}!\n"
            "Para continuar, ingresa el código de acceso que te haya sido entregado (Empleada o Patron):",
            parse_mode="Markdown",
        )
        return SELECT_ROLE

    await update.message.reply_text("❓ Opción no reconocida.")
    return ADMIN_MENU

# ----------------------------------------------------------------------
#  ADMIN – gestión de productos (add / delete)
# ----------------------------------------------------------------------
async def admin_gestion_prod(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # (existing code unchanged)
    opt = (update.message.text or "").strip()
    if opt == "🔙 Volver":
        await _show_main_menu(update, context, "admin")
        return ADMIN_MENU
    if opt == "Agregar producto":
        # Iniciar flujo de crear un nuevo producto (mantener flujo existente)
        await update.message.reply_text("🆕 *Nombre del producto*:", parse_mode="Markdown")
        return ADMIN_GESTION_PROD_NOMBRE
    if opt == "Agregar stock":
        # Iniciar flujo de agregar stock – muestra botones con productos existentes + "Nuevo producto"
        products = [p["nombre_producto"] for p in list_inventory()]
        options = products + ["Nuevo producto"]
        await update.message.reply_text('🔧 *Selecciona un producto para agregar stock* (o "Nuevo producto"):',
                                    reply_markup=_mk_keyboard(options),
                                    parse_mode="Markdown")
        return ADMIN_AGREGAR_STOCK_SEL
    if opt == "Eliminar producto":
        await update.message.reply_text("❌ *Nombre del producto a eliminar*:", parse_mode="Markdown")
        return ADMIN_ELIMINAR_PROD
    if opt == "Eliminar stock":
        # Mostrar lista de productos existentes para eliminar stock
        products = [p["nombre_producto"] for p in list_inventory()]
        await update.message.reply_text('🔧 *Selecciona un producto para eliminar stock*:',
                                    reply_markup=_mk_keyboard(products),
                                    parse_mode="Markdown")
        return ADMIN_ELIMINAR_STOCK_SEL
    if opt == "🔙 Volver":
        await _show_main_menu(update, context, "admin")
        return ADMIN_MENU
    await update.message.reply_text("❓ Opción no válida.")
    return ADMIN_GESTION_PROD

async def admin_agregar_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_prod"] = {"nombre": update.message.text.strip()}
    await update.message.reply_text("📦 *Cantidad inicial*:", parse_mode="Markdown")
    return ADMIN_GESTION_PROD_CANT

async def admin_agregar_cantidad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        cant = int(update.message.text.strip())
        if cant < 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Ingresa un entero positivo.")
        return ADMIN_GESTION_PROD_CANT
    context.user_data["new_prod"]["cantidad"] = cant
    await update.message.reply_text("💲 *Precio base*:", parse_mode="Markdown")
    return ADMIN_GESTION_PROD_BASE

async def admin_agregar_precio_base(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Check if the product already exists – if so, just increase its stock
    prod_name = context.user_data["new_prod"]["nombre"]
    existing = get_product(prod_name)
    if existing:
        # Increase stock by the quantity already entered
        cantidad = context.user_data["new_prod"]["cantidad"]
        update_stock(prod_name, cantidad)
        await update.message.reply_text(
            f"✅ Stock del producto '{prod_name}' actualizado. Cantidad total: {existing['cantidad'] + cantidad}",
            parse_mode="Markdown",
        )
        await _show_main_menu(update, context, "admin")
        return ADMIN_MENU
    # Otherwise, ask for the base price as usual
    try:
        precio = float(update.message.text.strip())
        if precio < 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Ingresa un número válido.")
        return ADMIN_GESTION_PROD_BASE
    context.user_data["new_prod"]["precio_base"] = precio
    await update.message.reply_text("📈 *Precio mínimo de venta*:", parse_mode="Markdown")
    return ADMIN_GESTION_PROD_MIN

async def admin_agregar_precio_min(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        precio_min = float(update.message.text.strip())
        if precio_min < 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Ingresa un número válido.")
        return ADMIN_GESTION_PROD_MIN
    prod = context.user_data["new_prod"]
    prod["precio_minimo"] = precio_min
    try:
        add_product(
            nombre_producto=prod["nombre"],
            cantidad=prod["cantidad"],
            precio_base=prod["precio_base"],
            precio_minimo_venta=prod["precio_minimo"],
        )
        await update.message.reply_text(f"✅ Producto '{prod['nombre']}' agregado.")
    except Exception as e:
        log.exception("Error al agregar producto")
        await update.message.reply_text(f"❌ Error al agregar producto: {e}")
    finally:
        context.user_data.pop("new_prod", None)
    await _show_main_menu(update, context, "admin")
    return ADMIN_MENU

async def admin_eliminar_producto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    nombre = update.message.text.strip()
    try:
        remove_product(nombre)
        await update.message.reply_text(f"✅ Producto '{nombre}' eliminado.")
    except Exception as e:
        log.exception("Error al eliminar producto")
        await update.message.reply_text(f"❌ Error: {e}")
    await _show_main_menu(update, context, "admin")
    return ADMIN_MENU

# ----------------------------------------------------------------------
#  ADMIN – agregar stock o crear nuevo producto (un flujo unificado)
# ----------------------------------------------------------------------
async def admin_agregar_stock_sel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text.strip()
    if choice == "Nuevo producto":
        # reutiliza el flujo existente de creación de producto
        await update.message.reply_text("🆕 *Nombre del nuevo producto*:", parse_mode="Markdown")
        return ADMIN_GESTION_PROD_NOMBRE
    # Producto existente: preguntar cantidad a agregar
    context.user_data["stock_target"] = {"producto": choice}
    await update.message.reply_text("📦 *Cantidad a agregar al stock*:", parse_mode="Markdown")
    return ADMIN_AGREGAR_STOCK_CANT

async def admin_agregar_stock_cant(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        cant = int(update.message.text.strip())
        if cant <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Ingresa un número entero positivo.")
        return ADMIN_AGREGAR_STOCK_CANT
    prod = context.user_data["stock_target"]["producto"]
    try:
        update_stock(prod, cant)
        await update.message.reply_text(f"✅ Stock del producto '{prod}' actualizado.")
    except Exception as e:
        log.exception("Error al actualizar stock")
        await update.message.reply_text(f"❌ Error al actualizar stock: {e}")
    await _show_main_menu(update, context, "admin")
    return ADMIN_MENU

# ----------------------------------------------------------------------
#  ADMIN – eliminar stock (un flujo separado)
# ----------------------------------------------------------------------
async def admin_eliminar_stock_sel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Selección de producto para eliminar stock
    choice = update.message.text.strip()
    context.user_data["stock_target"] = {"producto": choice}
    await update.message.reply_text("📦 *Cantidad a eliminar del stock*:", parse_mode="Markdown")
    return ADMIN_ELIMINAR_STOCK_CANT

async def admin_eliminar_stock_cant(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        cant = int(update.message.text.strip())
        if cant <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Ingresa un número entero positivo.")
        return ADMIN_ELIMINAR_STOCK_CANT
    prod = context.user_data["stock_target"]["producto"]
    try:
        # Restar stock (negativo) – update_stock valida cantidad mínima
        update_stock(prod, -cant)
        await update.message.reply_text(f"✅ Stock del producto '{prod}' actualizado (se eliminaron {cant} unidades).")
    except Exception as e:
        log.exception("Error al eliminar stock")
        await update.message.reply_text(f"❌ Error al eliminar stock: {e}")
    await _show_main_menu(update, context, "admin")
    return ADMIN_MENU

# ----------------------------------------------------------------------
#  ADMIN – registrar pagos administrativos (valor directo)
# ----------------------------------------------------------------------
async def admin_registrar_pago_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Permite volver al menú
    text = update.message.text.strip()
    if text == "🔙 Volver":
        await _show_main_menu(update, context, "admin")
        return ADMIN_MENU
    try:
        monto = float(text)
        if monto <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Ingresa un monto válido.")
        return ADMIN_REGISTRO_PAGOS
    # Determinar tipo de gasto según categoría seleccionada
    categoria = context.user_data.get("admin_payment", {}).get("categoria", "Otro")
    tipo_map = {"Agua": "servicios", "Luz": "servicios", "Internet": "servicios", "Otro": "operativo_bar"}
    tipo_gasto = tipo_map.get(categoria, "operativo_bar")
    # Use custom description if provided (for "Otro")
    custom_desc = context.user_data.get("admin_payment", {}).get("descripcion")
    descripcion = custom_desc if custom_desc else f"Pago administrativo - {categoria}"
    record_expense(tipo_gasto, descripcion, monto)
    await update.message.reply_text(f"✅ Pago administrativo registrado ({categoria}).")
    await _show_main_menu(update, context, "admin")
    return ADMIN_MENU

async def admin_registrar_pago_cat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Handles category selection for administrative payments
    choice = (update.message.text or "").strip()
    if choice == "🔙 Volver":
        await _show_main_menu(update, context, "admin")
        return ADMIN_MENU
    if choice not in ["Agua", "Luz", "Internet", "Otro"]:
        await update.message.reply_text("❌ Selecciona una opción válida.")
        return ADMIN_REGISTRO_PAGOS_CAT
    # Store selected category
    context.user_data.setdefault("admin_payment", {})["categoria"] = choice
    if choice == "Otro":
        # Ask for custom description before amount
        await update.message.reply_text(
            "✏️ *Ingresa una descripción para el pago (Otro)*:",
            parse_mode="Markdown",
            reply_markup=_mk_keyboard(["🔙 Volver"]),
        )
        return ADMIN_REGISTRO_PAGOS_DESC
    else:
        await update.message.reply_text(
            f"💰 *Ingresa el monto del pago administrativo ({choice})*:",
            parse_mode="Markdown",
            reply_markup=_mk_keyboard(["🔙 Volver"]),
        )
        return ADMIN_REGISTRO_PAGOS

async def admin_registrar_pago_desc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Captura la descripción personalizada para la categoría "Otro"
    text = (update.message.text or "").strip()
    if text == "🔙 Volver":
        await _show_main_menu(update, context, "admin")
        return ADMIN_MENU
    # Store description
    context.user_data.setdefault("admin_payment", {})["descripcion"] = text
    # Ask for the amount
    await update.message.reply_text(
        "💰 *Ingresa el monto del pago administrativo*:",
        parse_mode="Markdown",
        reply_markup=_mk_keyboard(["🔙 Volver"]),
    )
    return ADMIN_REGISTRO_PAGOS
# ----------------------------------------------------------------------
#  ADMIN – reportes (texto / PDF)
# ----------------------------------------------------------------------
async def reportes_tipo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = (update.message.text or "").strip()
    if choice == "🔙 Volver":
        await _show_main_menu(update, context, "admin")
        return ADMIN_MENU
    if choice not in ("Texto", "PDF"):
        await update.message.reply_text("❌ Elige Texto o PDF.")
        return REPOPT_TIPO
    if "reporte" not in context.user_data:
        context.user_data["reporte"] = {}
    context.user_data["reporte"]["formato"] = choice
    await update.message.reply_text(
        "📆 *Ingresa el año del reporte* (ej. 2026):",
        parse_mode="Markdown",
    )
    return REPOPT_ANO
async def reportes_ano(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Captura el año para el reporte
    text = (update.message.text or "").strip()
    if text == "🔙 Volver":
        await _show_main_menu(update, context, "admin")
        return ADMIN_MENU
    try:
        year = int(text)
        if year < 2000 or year > 2100:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Ingresa un año válido (ej. 2026).")
        return REPOPT_ANO
    if "reporte" not in context.user_data:
        context.user_data["reporte"] = {}
    context.user_data["reporte"]["year"] = year
    await update.message.reply_text("📆 *Ingresa el mes del reporte* (ej. JUNIO):", parse_mode="Markdown")
    return REPOPT_MES

async def reportes_mes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_input = update.message.text.strip()
    if user_input == "🔙 Volver":
        await _show_main_menu(update, context, "admin")
        return ADMIN_MENU

    mes = user_input.capitalize()
    spanish_months = {
        "Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4,
        "Mayo": 5, "Junio": 6, "Julio": 7, "Agosto": 8,
        "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12,
    }
    if mes not in spanish_months:
        await update.message.reply_text(
            "❌ Mes no válido. Usa el nombre completo en español (Enero, Febrero, ...)."
        )
        return REPOPT_MES
    context.user_data["reporte"]["mes"] = mes
    context.user_data["reporte"]["month_num"] = spanish_months[mes]
    await update.message.reply_text(
        "📅 *Ingresa el rango de días del mes* (ej. 1-22 o 13-15):",
        parse_mode="Markdown",
        reply_markup=_mk_keyboard(["🔙 Volver"]),
    )
    return REPOPT_RANGO

# ----------------------------------------------------------------------
#  Inline button callbacks (payment handling, week selection, etc.)
# ----------------------------------------------------------------------
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data

    if data.startswith("pago_total:"):
        parts = data.split(":")
        # Handle "all" case (bulk operation) – not implemented
        if parts[1] == "all":
            await query.answer()
            await query.message.reply_text("⚠️ Operación masiva de Pago Total no está disponible.")
            return
        sale_id = int(parts[1])
        # Ask payment method
        context.user_data["pending_payment"] = {"id": sale_id, "type": "total"}
        await query.answer()
        await query.message.reply_text(
            "💳 Selecciona método de pago para el total:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Transferencia", callback_data=f"pago_method:{sale_id}:transfer"),
                 InlineKeyboardButton("Efectivo", callback_data=f"pago_method:{sale_id}:cash")]
            ])
        )

    elif data.startswith("abono:"):
        parts = data.split(":")
        if parts[1] == "all":
            await query.answer()
            await query.message.reply_text("⚠️ Operación masiva de Abono no está disponible.")
            return
        sale_id = int(parts[1])
        # Ask payment method first
        context.user_data["pending_payment"] = {"id": sale_id, "type": "abono"}
        await query.answer()
        await query.message.reply_text(
            "💳 Selecciona método de pago para el abono:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Transferencia", callback_data=f"abono_method:{sale_id}:transfer"),
                 InlineKeyboardButton("Efectivo", callback_data=f"abono_method:{sale_id}:cash")]
            ])
        )

    elif data.startswith("pago_method:"):
        # data format: pago_method:{sale_id}:{method}
        _, sale_id_str, method = data.split(":")
        sale_id = int(sale_id_str)
        try:
            mark_payment_full(sale_id, metodo_pago=method)
            await query.answer(f"✅ Pago total registrado vía {method}")
        except Exception as e:
            log.exception("Error al registrar pago total")
            await query.answer(f"❌ Error: {e}", show_alert=True)
        # Clean pending
        context.user_data.pop("pending_payment", None)
        await query.message.edit_reply_markup(reply_markup=None)

    elif data.startswith("abono_method:"):
        # data format: abono_method:{sale_id}:{method}
        _, sale_id_str, method = data.split(":")
        sale_id = int(sale_id_str)
        # Store method and ask amount
        context.user_data["abono_pending"] = sale_id
        context.user_data["abono_method"] = method
        await query.answer()
        await query.message.reply_text("💵 *Monto del abono*:", parse_mode="Markdown")
    elif data.startswith("cobro_cliente:"):
        client = data.split(":", 1)[1]
        grouped = context.user_data.get("cobro_grouped", {})
        items = grouped.get(client, [])
        if not items:
            await query.answer("❌ No hay cuentas para este cliente.", show_alert=True)
            return
        lines = [f"*Cuentas de {client}:*"]
        total = 0.0
        for it in items:
            lines.append(f"{it['cantidad']} {it['producto']} - {_fmt_money(it['subtotal'])}")
            total += it['subtotal']
        lines.append(f"Total: {_fmt_money(total)}")
        keyboard = [[
            InlineKeyboardButton("💰 Pago Total", callback_data=f"cobro_pago_total:{client}"),
            InlineKeyboardButton("💸 Abono", callback_data=f"cobro_abono:{client}"),
        ]]
        await query.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data.startswith("cobro_pago_total:"):
        client = data.split(":", 1)[1]
        await query.answer()
        await query.message.reply_text(
            f"💳 Selecciona método de pago para el pago total de *{client}*:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Transferencia", callback_data=f"cobro_pago_metodo:{client}:transfer"),
                 InlineKeyboardButton("Efectivo", callback_data=f"cobro_pago_metodo:{client}:cash")]
            ])
        )
    elif data.startswith("cobro_pago_metodo:"):
        _, client, method = data.split(":", 2)
        pending = query_pending_payments()
        for p in pending:
            if p['cliente'] == client:
                try:
                    mark_payment_full(p['id'], metodo_pago=method)
                except Exception as e:
                    log.exception("Error al registrar pago total por cliente")
        await query.answer(f"✅ Pagos totales registrados para {client} vía {method}")
        await query.message.edit_reply_markup(reply_markup=None)
        await query.message.reply_text("✅ Pagos procesados.")
        await _show_main_menu(update, context, "empleado")
    elif data.startswith("cobro_abono:"):
        client = data.split(":", 1)[1]
        await query.answer()
        await query.message.reply_text(
            f"💳 Selecciona método de pago para el abono de *{client}*:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Transferencia", callback_data=f"cobro_abono_metodo:{client}:transfer"),
                 InlineKeyboardButton("Efectivo", callback_data=f"cobro_abono_metodo:{client}:cash")]
            ])
        )
    elif data.startswith("cobro_abono_metodo:"):
        _, client, method = data.split(":", 2)
        await query.answer()
        context.user_data["cobro_abono_pending"] = client
        context.user_data["cobro_abono_metodo"] = method
        context.user_data["awaiting_abono"] = True
        await query.message.reply_text(f"💸 Ingrese el monto de abono para {client}:", parse_mode="Markdown")
    elif data == "cobro_volver":
        # Return to client selection list
        grouped = context.user_data.get("cobro_grouped", {})
        client_buttons = [
            InlineKeyboardButton(cliente, callback_data=f"cobro_cliente:{cliente}")
            for cliente in grouped.keys()
        ]
        client_buttons.append(InlineKeyboardButton("🔙 Volver", callback_data="cobro_volver"))
        await query.message.edit_text("💳 Selecciona el cliente:", reply_markup=InlineKeyboardMarkup([client_buttons]))
        context.user_data["awaiting_abono"] = True

    else:
        await query.answer("❓ Acción no reconocida.", show_alert=True)

# ----------------------------------------------------------------------
#  ADMIN – rango de días personalizado
# ----------------------------------------------------------------------
async def reportes_rango(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    if text == "🔙 Volver":
        await update.message.reply_text(
            "¿Qué formato deseas?",
            reply_markup=_mk_keyboard(["Texto", "PDF", "🔙 Volver"]),
        )
        return REPOPT_TIPO

    m = re.match(r"^(\d{1,2})\s*[-–]\s*(\d{1,2})$", text)
    if not m:
        await update.message.reply_text(
            "❌ Formato inválido. Usa inicio-fin, ej: 1-22",
            reply_markup=_mk_keyboard(["🔙 Volver"]),
        )
        return REPOPT_RANGO

    start_day = int(m.group(1))
    end_day = int(m.group(2))
    if start_day < 1 or end_day > 31 or start_day > end_day:
        await update.message.reply_text("❌ Rango inválido (1-31, inicio ≤ fin).")
        return REPOPT_RANGO

    context.user_data["reporte"]["start_day"] = start_day
    context.user_data["reporte"]["end_day"] = end_day
    await reportes_confirm(update, context)
    return ADMIN_MENU

async def reportes_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Genera y envía el reporte en texto (fecha, producto y total por producto)."""
    rpt = context.user_data["reporte"]
    mes = rpt["mes"]
    month_num = rpt.get("month_num")
    start_day = rpt.get("start_day")
    end_day = rpt.get("end_day")
    if not all([month_num, start_day, end_day]):
        await update.effective_message.reply_text("❌ Faltan datos del reporte.")
        return ADMIN_MENU
    # Consultas DB (PostgreSQL)
    from db import _connect
    from psycopg2.extras import RealDictCursor
    conn = _connect()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT fecha::date AS fecha, producto,
                   SUM(cantidad)::int AS cantidad, SUM(subtotal) AS total
            FROM ventas_pedidos
            WHERE EXTRACT(MONTH FROM fecha) = %s
            GROUP BY fecha::date, producto
            ORDER BY fecha::date, producto
            """,
            (month_num,)
        )
        ventas = [dict(r) for r in cur.fetchall()]
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT fecha, descripcion, monto FROM gastos WHERE EXTRACT(MONTH FROM fecha) = %s",
            (month_num,)
        )
        gastos = [dict(r) for r in cur.fetchall()]
    conn.close()
    # Filtrar por rango de días
    ventas_filtradas = [v for v in ventas if start_day <= v["fecha"].day <= end_day]
    gastos_filtrados = [g for g in gastos if start_day <= g["fecha"].day <= end_day]
    # Consolidar por fecha + producto (case-insensitive)
    consolidated = {}
    for v in ventas_filtradas:
        key = (v["fecha"], v["producto"].lower())
        if key not in consolidated:
            consolidated[key] = {
                "fecha": v["fecha"],
                "producto": v["producto"],
                "cantidad": v["cantidad"],
                "total": v["total"],
            }
        else:
            consolidated[key]["cantidad"] += v["cantidad"]
            consolidated[key]["total"] += v["total"]
    ventas_agrupadas = sorted(consolidated.values(), key=lambda x: (x["fecha"], x["producto"].lower()))
    # Formatear reporte
    def _fmt_money(value: float) -> str:
        if FORMATO_MILES:
            return f"{SIGNO_MONEDA}{int(value):,}".replace(",", ".")
        return f"{SIGNO_MONEDA}{value:.2f}"
    lines = [
        f"📊 *Reporte – {NOMBRE_NEGOCIO}*",
        f"*Mes:* {mes}",
        f"*Rango:* {start_day} al {end_day}",
        "",
        "*Ventas (fecha, producto, cantidad, total)*",
        "----------------------------",
    ]
    if not ventas_agrupadas:
        lines.append("_Sin ventas en el periodo seleccionado_")
    else:
        for v in ventas_agrupadas:
            fecha_str = v["fecha"].strftime("%d/%m") if hasattr(v["fecha"], "strftime") else str(v["fecha"])
            lines.append(f"{fecha_str}\t{v['cantidad']}\t{v['producto']}\t{_fmt_money(v['total'])}")
    lines.extend([
        "",
        "*Gastos*",
        "----------------------------",
    ])
    if not gastos_filtrados:
        lines.append("_Sin gastos en el periodo seleccionado_")
    else:
        for g in sorted(gastos_filtrados, key=lambda x: x["fecha"]):
            fecha = g["fecha"].strftime("%d/%m")
            desc = g.get('descripcion') or g.get('tipo')
            lines.append(f"{fecha}\t{desc}:\t{_fmt_money(g['monto'])}")
    total_ventas = sum(v["total"] for v in ventas_agrupadas)
    total_gastos = sum(g["monto"] for g in gastos_filtrados)
    neto = total_ventas - total_gastos
    lines.extend([
        "",
        "*TOTALES*",
        f"Ventas:\t{_fmt_money(total_ventas)}",
        f"Gastos:\t{_fmt_money(total_gastos)}",
        f"🟢 Neto:\t{_fmt_money(neto)}",
    ])
    await update.effective_message.reply_text("\n".join(lines), parse_mode="Markdown")
    context.user_data.pop("reporte", None)
    await _show_main_menu(update, context, "admin")
    return ADMIN_MENU
# ----------------------------------------------------------------------
#  Fallback for unexpected messages (including pending partial payment amount)
# ----------------------------------------------------------------------
async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles unexpected messages, including pending abono inputs.
    """
    # If we are waiting for an abono (partial payment) input
    if context.user_data.get("awaiting_abono"):
        # ----- Client‑wide abono (triggered from the "cobro_abono" button) -----
        if "cobro_abono_pending" in context.user_data:
            client = context.user_data.pop("cobro_abono_pending")
            method = context.user_data.pop("cobro_abono_metodo", "Desconocido")
            try:
                monto = float(update.message.text.strip())
                pending = query_pending_payments()
                applied = 0
                for p in pending:
                    if p["cliente"] == client:
                        try:
                            register_partial_payment(p["id"], monto, metodo_pago=method)
                            applied += 1
                        except Exception as e:
                            log.exception(
                                f"Error registering partial payment for sale {p['id']}"
                            )
                await update.message.reply_text(
                    f"✅ Abono de {_fmt_money(monto)} registrado para {applied} venta(s) del cliente {client}."
                )
                await _show_main_menu(update, context, "empleado")
            except Exception as e:
                log.exception("Error al registrar abono del cliente")
                await update.message.reply_text(f"❌ Error al registrar abono: {e}")
        # ----- Single‑sale abono (previous flow) -----
        else:
            try:
                monto = float(update.message.text.strip())
                sale_id = context.user_data.pop("abono_pending")
                method = context.user_data.pop("abono_method", "Desconocido")
                register_partial_payment(sale_id, monto, metodo_pago=method)
                await update.message.reply_text("✅ Abono registrado.")
                await _show_main_menu(update, context, "empleado")
            except Exception as e:
                log.exception("Error al registrar abono")
                await update.message.reply_text(f"❌ Error: {e}")
        # Reset the flag regardless of which branch ran
        context.user_data["awaiting_abono"] = False
        return
    # --------------------------------------------------------------------
    # Fallback for any other unexpected text
    # --------------------------------------------------------------------
    await update.message.reply_text(
        "❓ No entiendo esa instrucción. Usa el menú."
    )

# ------------------------------------------------------------
#  /reset – elimina tu registro y vuelve a iniciar sesión
# ------------------------------------------------------------
async def reset_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    # Remove user record from PostgreSQL (using the helper)
    from db import delete_user
    delete_user(user_id)
    await update.message.reply_text(
        "🔄 Registro eliminado. Usa /start para volver a ingresar el código de acceso.",
        parse_mode="Markdown",
    )
    return ConversationHandler.END