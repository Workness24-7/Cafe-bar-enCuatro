import logging
import os
from telegram.ext import Application, ConversationHandler, CommandHandler, MessageHandler, filters
from bot_handlers import (
    start, select_role, employee_menu,
    SELECT_ROLE, EMPLOYEE_MENU, ADMIN_MENU,
    VENTA_CLIENTE, ADMIN_REGISTRO_PAGOS, REPOPT_TIPO
)

logging.basicConfig(level=logging.INFO)

async def admin_router(update, context):
    # Redirige de forma segura las opciones de administrador hacia la lógica de validación
    return await select_role(update, context)

def main():
    TOKEN = os.getenv("TOKEN_TELEGRAM") or os.getenv("TOKEN")
    if not TOKEN:
        raise ValueError("No se encontró la variable de Token de Telegram")

    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            # Estado de inicio para contraseñas
            SELECT_ROLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_role)],
            
            # Estados independientes para evitar que las funciones choquen entre sí
            ADMIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_router)],
            EMPLOYEE_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, employee_menu)],
            
            # Sub-estados de los flujos secundarios
            VENTA_CLIENTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, employee_menu)],
            ADMIN_REGISTRO_PAGOS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_router)],
            REPOPT_TIPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_router)]
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    )

    application.add_handler(conv_handler)
    print("🚀 Router de navegación activado en el sistema...")
    application.run_polling()

if __name__ == '__main__':
    main()
