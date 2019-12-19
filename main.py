import os
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Callable, Union

import telegram
# https://github.com/Awethon/open-api-python-client?files=1
from openapi_client import openapi
from openapi_genclient import Operation, OperationTypeWithCommission, Currency
from pytz import timezone, utc

DEFAULT_CURRENCY = Currency.RUB
bot = telegram.Bot(token=os.environ["TELEGRAM_TOKEN"])


def get_tinkoff_invest_client(token):
    return openapi.api_client(token)


def format_dict(data: Dict):
    return '; '.join(f'{k}: {v}' for k, v in data.items())


class InvestCalculator:
    commission_operations_types = (
        OperationTypeWithCommission.BROKERCOMMISSION,
        OperationTypeWithCommission.SERVICECOMMISSION,
        OperationTypeWithCommission.TAXDIVIDEND,
        OperationTypeWithCommission.TAXCOUPON
    )

    def __init__(self, client, date_from: datetime = None, date_to: datetime = None):
        self.client = client
        self.date_to = date_to or datetime.now(tz=timezone('Europe/Moscow'))
        self.date_from = date_from or datetime(2001, 1, 1, tzinfo=utc)
        self._operations = None

    @property
    def operations(self):
        if self._operations is None:
            self._operations = self.get_all_operations()
        return self._operations

    def get_all_operations(self) -> List[Operation]:
        return self.client.operations.operations_get(
            _from=self.date_from.isoformat(), to=self.date_to.isoformat()
        ).payload.operations

    def get_total_payment_by_filter(self, func: Union[Callable, None] = None) -> Dict[str, float]:
        result = defaultdict(float)
        for operation in filter(func, self.operations):
            result[operation.currency] += operation.payment
        return result

    def get_commissions(self) -> Dict[str, float]:
        return self.get_total_payment_by_filter(lambda o: o.operation_type in self.commission_operations_types)

    def get_pay_in(self):
        return self.get_total_payment_by_filter(lambda o: o.operation_type == OperationTypeWithCommission.PAYIN)

    def get_pay_out(self):
        return self.get_total_payment_by_filter(lambda o: o.operation_type == OperationTypeWithCommission.PAYOUT)

    def get_pay_total(self):
        return self.get_total_payment_by_filter(
            lambda o: o.operation_type in (OperationTypeWithCommission.PAYOUT, OperationTypeWithCommission.PAYIN)
        )

    def get_balance(self):
        return self.get_total_payment_by_filter(lambda o: o.currency == DEFAULT_CURRENCY)

    def get_total_operations_balance(self):
        return self.get_total_payment_by_filter(
            lambda o: (
                    o.currency == DEFAULT_CURRENCY and
                    o.operation_type in (OperationTypeWithCommission.BUY, OperationTypeWithCommission.SELL, 'BuyCard')
            )
        )

    def get_name_by_figi(self, figi):
        position = self.client.market.market_search_by_figi_get(figi).payload
        return f'{position.ticker} - {position.name} ({figi})'

    def get_profit(self) -> Dict[str, float]:
        profit = dict()
        profit['dividend'] = self.get_total_payment_by_filter(
            lambda o: (o.operation_type in (
            OperationTypeWithCommission.DIVIDEND, OperationTypeWithCommission.TAXDIVIDEND)
                       and o.currency == DEFAULT_CURRENCY)
        ).get(DEFAULT_CURRENCY, 0.0)
        profit['coupon'] = self.get_total_payment_by_filter(
            lambda o: (o.operation_type in (OperationTypeWithCommission.COUPON, OperationTypeWithCommission.TAXCOUPON)
                       and o.currency == DEFAULT_CURRENCY)
        ).get(DEFAULT_CURRENCY, 0.0)

        figi_total = defaultdict(float)
        for operation in filter(
                lambda o: (
                        o.currency == DEFAULT_CURRENCY and
                        o.operation_type in (
                        OperationTypeWithCommission.BUY, OperationTypeWithCommission.SELL, 'BuyCard') and
                        o.payment != 0
                ),
                self.operations
        ):
            figi_total[operation.figi] += operation.payment + operation.commission.value

        figi_in_portfolio = {
            f.figi: f.ticker for f in self.client.portfolio.portfolio_get().payload.positions
        }
        for figi, p_sum in figi_total.items():
            if figi not in figi_in_portfolio:
                profit[self.get_name_by_figi(figi)] = p_sum

        return profit

    def get_statistics_str(self) -> str:
        profit = self.get_profit()
        message = f"Commissions and Taxes -> {format_dict(self.get_commissions())}\n" \
                  f"Pay In -> {format_dict(self.get_pay_in())}\n" \
                  f"Pay Out {format_dict(self.get_pay_out())}\n" \
                  f"Pay Total -> {format_dict(self.get_pay_total())}\n" \
                  f"Operations -> {format_dict(self.get_total_operations_balance())}\n" \
                  f"Total Profit -> {sum(profit.values())}\n" \
                  f"Detailed Profit -> {format_dict(profit)}"

        return message


def webhook(request):
    if request.method == "POST":
        update = telegram.Update.de_json(request.get_json(force=True), bot)
        chat_id = update.message.chat.id
        token = update.message.text
        calculator = InvestCalculator(get_tinkoff_invest_client(token))
        bot.sendMessage(chat_id=chat_id, text=calculator.get_statistics_str())
    return "ok"