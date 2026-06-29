import logging
import os
from telegram.ext import Application, ConversationHandler, CommandHandler, MessageHandler, filters
from bot_handlers import (
    start, select_role, employee_menu,
    SELECT_ROLE, EMPLOYEE_MENU, ADMIN_MENU,
    VENTA_CLIENTE, ADMIN_REGISTRO_PAGOS, REPOPT_TIPO
)

logging.basicConfig(level=logging.INFO)

def main():
    TOKEN = os.getenv("TOKEN_TELEGRAM") or os.getenv("TOKEN")
    if not TOKEN:
        raise ValueError("No se encontró la variable de Token de Telegram")

    application = Application.builder().token(TOKEN).build()

    # MAPA DE NAVEGACIÓN COMPLETO Y PROFESIONAL
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            # Estado 0: Validación de contraseñas
            SELECT_ROLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_role)],
            
            # Estado 1: Menú de Administrador (Escucha y procesa los botones del patrón)
            ADMIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_role)], 
            
            # Estado 2: Menú de Empleado (Escucha y procesa los botones de la empleada)
            EMPLOYEE_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, employee_menu)],
            
            # Sub-estados para los flujos del bar (Se activan al tocar los botones)
            VENTA_CLIENTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, employee_menu)],
            ADMIN_REGISTRO_PAGOS: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_role)],
            REPOPT_TIPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_role)]
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    )

    application.add_handler(conv_handler)
    
    # Manejador de respaldo para asegurar que los menús siempre respondan ante el texto de los botones
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, select_role))
    
    print("🚀 El Bot del Bar se ha encendido con el mapa completo...")
    application.run_polling()

if __name__ == '__main__':
    main()
