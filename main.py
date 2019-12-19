import os

import telegram

from common import InvestCalculator, get_tinkoff_invest_client

bot = telegram.Bot(token=os.environ["TELEGRAM_TOKEN"])


def webhook(request):
    if request.method == "POST":
        update = telegram.Update.de_json(request.get_json(force=True), bot)
        chat_id = update.message.chat.id
        token = update.message.text
        calculator = InvestCalculator(get_tinkoff_invest_client(token))
        bot.sendMessage(chat_id=chat_id, text=calculator.get_statistics_str())
    return "ok"
