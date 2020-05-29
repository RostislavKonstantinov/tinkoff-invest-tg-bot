import logging
import os

import telegram
from telegram.ext import CommandHandler, Dispatcher

from common import InvestCalculator, get_tinkoff_invest_client

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


def error(update, context):
    """Log Errors caused by Updates."""
    logger.warning(f'Caused error "{context.error}" update "{update}"' )
    update.message.reply_text('Token is invalid or empty.')


def get_calculator(context):
    token = context.args[0]
    return InvestCalculator(get_tinkoff_invest_client(token))


def statistics(update, context):
    calculator = get_calculator(context)
    message = calculator.get_statistics_str()
    update.message.reply_text(message)


def portfolio(update, context):
    calculator = get_calculator(context)
    data = calculator.get_portfolio_info()
    message = ';'.join(data[0].keys()) + '\n' if data else ''
    message += '\n'.join([';'.join([str(val) for val in line.values()]) for line in data])
    update.message.reply_text(message)


bot = telegram.Bot(token=os.environ['TELEGRAM_TOKEN'])
dp = Dispatcher(bot, None, workers=0, use_context=True)
dp.add_handler(CommandHandler('s', statistics))  # statistics
dp.add_handler(CommandHandler('p', portfolio))  # portfolio
# log all errors
dp.add_error_handler(error)


def webhook(request):
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dp.process_update(update)
