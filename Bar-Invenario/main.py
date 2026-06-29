import logging
import os
from telegram.ext import Application, ConversationHandler, CommandHandler, MessageHandler, filters
from bot_handlers import start, select_role, employee_menu, SELECT_ROLE, EMPLOYEE_MENU, ADMIN_MENU

logging.basicConfig(level=logging.INFO)

def main():
    TOKEN = os.getenv("TOKEN_TELEGRAM")
    if not TOKEN:
        raise ValueError("No se encontró la variable TOKEN_TELEGRAM")

    application = Application.builder().token(TOKEN).build()

    # MAPA CORREGIDO: Ahora el bot sabe escuchar el menú administrativo y el de empleado
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECT_ROLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_role)],
            EMPLOYEE_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, employee_menu)],
            ADMIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_role)], 
        },
        fallbacks=[CommandHandler("start", start)],
    )

    # Añadimos manejadores globales para que los menús siempre respondan ante texto
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, select_role))
    
    print("🚀 El Bot del Bar se ha encendido correctamente...")
    application.run_polling()

if __name__ == '__main__':
    main()
