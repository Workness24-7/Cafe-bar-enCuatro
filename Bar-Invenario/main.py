# main.py
import asyncio
import logging
import os
from pathlib import Path

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

from config import TOKEN_TELEGRAM
from db import init_db
# Import handlers and states from bot_handlers
from bot_handlers import (
    start,
    select_role,
    employee_menu,
    admin_menu,
    venta_cliente,
    venta_multiple_input,
    venta_producto,
    venta_cantidad,
    venta_precio,
    venta_estado,
    venta_abono,
    admin_gestion_prod,
    admin_agregar_nombre,
    admin_agregar_cantidad,
    admin_agregar_precio_base,
    admin_agregar_precio_min,
    admin_eliminar_producto,
    admin_agregar_stock_sel,
    admin_agregar_stock_cant,
    admin_eliminar_stock_sel,
    admin_eliminar_stock_cant,
    reportes_tipo,
    reportes_mes,
    reportes_ano,
    reportes_rango,
    unknown_message,
    registrar_gasto_tipo,
    registrar_gasto_monto,
    button_callback,
    reset_user,
    admin_registrar_pago_admin,
    admin_registrar_pago_cat,
    admin_registrar_pago_desc,
    # Employee flow new handlers
    venta_producto_selection,
    venta_producto_new_name,
    venta_producto_new_cantidad,
    venta_producto_new_precio,
    venta_agregar_otro,
    venta_pago_estado,
    venta_pago_abono,
    venta_pago_metodo,
    venta_pago_metodo,
    # State constants
    ADMIN_REGISTRO_PAGOS,
    ADMIN_REGISTRO_PAGOS_CAT,
    ADMIN_REGISTRO_PAGOS_DESC,
    SELECT_ROLE,
    ADMIN_MENU,
    EMPLOYEE_MENU,
    VENTA_CLIENTE,
    VENTA_MULTIPLE_INPUT,
    VENTA_PRODUCTO,
    VENTA_PRODUCTO_SELECTION,
    VENTA_PRODUCTO_NEW_NAME,
    VENTA_PRODUCTO_NEW_CANTIDAD,
    VENTA_PRODUCTO_NEW_PRECIO,
    VENTA_CANTIDAD,
    VENTA_PRECIO,
    VENTA_ESTADO,
    VENTA_ABONO,
    VENTA_AGREGAR_OTRO,
    VENTA_PAGO_ESTADO,
    VENTA_PAGO_ABONO,
    VENTA_PAGO_METODO,
    ADMIN_GESTION_PROD,
    ADMIN_GESTION_PROD_NOMBRE,
    ADMIN_GESTION_PROD_CANT,
    ADMIN_GESTION_PROD_BASE,
    ADMIN_GESTION_PROD_MIN,
    ADMIN_ELIMINAR_PROD,
    ADMIN_AGREGAR_STOCK_SEL,
    ADMIN_AGREGAR_STOCK_CANT,
    ADMIN_ELIMINAR_STOCK_SEL,
    ADMIN_ELIMINAR_STOCK_CANT,
    REPOPT_TIPO,
    REPOPT_MES,
    REPOPT_RANGO,
    REPOPT_ANO,
    REGISTRO_GASTO_TIPO, REGISTRO_GASTO_MONTO,
)

# ----------------------------------------------------------------------
#  Logging configuration
# ----------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ----------------------------------------------------------------------
#  Main entry point (synchronous version)
# ----------------------------------------------------------------------
def main() -> None:
    # Ensure the SQLite database and tables exist before the bot starts
    init_db()

    # Build the Application (synchronous version of PTB)
    app = ApplicationBuilder().token(TOKEN_TELEGRAM).connect_timeout(180).read_timeout(180).build()

    # ------------------------------------------------------------
    #  ConversationHandler – usa los estados definidos en bot_handlers
    # ------------------------------------------------------------
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.COMMAND, start)],
        states={
            SELECT_ROLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_role)],
            ADMIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_menu)],
            EMPLOYEE_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, employee_menu)],
            # --- empleado venta flow ---
            VENTA_CLIENTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, venta_cliente)],
            VENTA_MULTIPLE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, venta_multiple_input)],
            VENTA_PRODUCTO_SELECTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, venta_producto_selection)],
            VENTA_PRODUCTO_NEW_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, venta_producto_new_name)],
            VENTA_PRODUCTO_NEW_CANTIDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, venta_producto_new_cantidad)],
            VENTA_PRODUCTO_NEW_PRECIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, venta_producto_new_precio)],
            VENTA_CANTIDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, venta_cantidad)],
            VENTA_PRECIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, venta_precio)],
            VENTA_ESTADO: [MessageHandler(filters.TEXT & ~filters.COMMAND, venta_estado)],
        VENTA_PAGO_METODO: [MessageHandler(filters.TEXT & ~filters.COMMAND, venta_pago_metodo)],
            VENTA_ABONO: [MessageHandler(filters.TEXT & ~filters.COMMAND, venta_abono)],
            VENTA_AGREGAR_OTRO: [MessageHandler(filters.TEXT & ~filters.COMMAND, venta_agregar_otro)],
            VENTA_PAGO_ESTADO: [MessageHandler(filters.TEXT & ~filters.COMMAND, venta_pago_estado)],
            VENTA_PAGO_ABONO: [MessageHandler(filters.TEXT & ~filters.COMMAND, venta_pago_abono)],
            VENTA_PAGO_ESTADO: [MessageHandler(filters.TEXT & ~filters.COMMAND, venta_pago_estado)],
            VENTA_PAGO_ABONO: [MessageHandler(filters.TEXT & ~filters.COMMAND, venta_pago_abono)],
            # --- admin gestión productos ---
            ADMIN_GESTION_PROD: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_gestion_prod)],
            ADMIN_GESTION_PROD_NOMBRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_agregar_nombre)],
            ADMIN_GESTION_PROD_CANT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_agregar_cantidad)],
            ADMIN_GESTION_PROD_BASE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_agregar_precio_base)],
            ADMIN_GESTION_PROD_MIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_agregar_precio_min)],
            ADMIN_ELIMINAR_PROD: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_eliminar_producto)],
            ADMIN_AGREGAR_STOCK_SEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_agregar_stock_sel)],
            ADMIN_AGREGAR_STOCK_CANT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_agregar_stock_cant)],
            ADMIN_ELIMINAR_STOCK_SEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_eliminar_stock_sel)],
            ADMIN_ELIMINAR_STOCK_CANT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_eliminar_stock_cant)],
            # --- reports ---
            REPOPT_TIPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, reportes_tipo)],
            REPOPT_ANO: [MessageHandler(filters.TEXT & ~filters.COMMAND, reportes_ano)],
            REGISTRO_GASTO_TIPO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_gasto_tipo),
                                            ],
            REGISTRO_GASTO_MONTO: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_gasto_monto)
                ],
                REPOPT_MES: [MessageHandler(filters.TEXT & ~filters.COMMAND, reportes_mes)],
            REPOPT_RANGO: [MessageHandler(filters.TEXT & ~filters.COMMAND, reportes_rango)],
            ADMIN_REGISTRO_PAGOS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_registrar_pago_admin)],
        ADMIN_REGISTRO_PAGOS_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_registrar_pago_cat)],
            ADMIN_REGISTRO_PAGOS_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_registrar_pago_desc)],
        },
        fallbacks=[MessageHandler(filters.COMMAND, unknown_message)],
        allow_reentry=True,
    )
    app.add_handler(conv_handler)

    # Command to reset login (delete user record)
    app.add_handler(CommandHandler("reset", reset_user))

    # Inline button callbacks (payment handling, week selection, etc.)
    app.add_handler(CallbackQueryHandler(button_callback))

    # Catch‑all for any unexpected text messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))

    # Global error handler – logs and notifies the user
    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.exception("Exception while handling an update:", exc_info=context.error)
        if update and update.effective_message:
            await update.effective_message.reply_text(
                f"⚠️ Ocurrió un error inesperado: {context.error}. Por favor, intenta de nuevo."
            )

    app.add_error_handler(error_handler)

    # Run the bot until stopped (polling mode)
    app.run_polling()

if __name__ == "__main__":
    # Windows specific event‑loop policy (optional – can be omitted)
    if os.name == "nt":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except Exception:
            pass
    main()
