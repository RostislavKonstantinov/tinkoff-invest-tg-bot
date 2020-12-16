from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Callable, Union, Iterator

# https://github.com/Awethon/open-api-python-client?files=1
from openapi_client import openapi
from openapi_genclient import Operation, OperationTypeWithCommission, Currency, InstrumentType
from pytz import timezone, utc

DEFAULT_CURRENCY = Currency.RUB


def get_tinkoff_invest_client(token):
    return openapi.api_client(token)


def amount_emoji(amount: float) -> str:
    emoji = '✅' if amount >= 0 else '❌'
    return f'{round(amount, 2)}{emoji}'


def format_dict(data: Dict):
    return '; '.join(f'{k}: {v}' for k, v in data.items())


def format_dict_with_emoji(data: Dict):
    result = ''
    for name, value in data.items():
        if isinstance(value, dict):
            result += f'{name}: {format_dict_with_emoji(value)}'
        elif isinstance(value, float):
            result += f'{name}: {amount_emoji(value)}; '
    return result


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

    def get_operations_by_filter(self, func: Union[Callable, None] = None) -> Iterator[Operation]:
        return filter(func, self.operations)

    def get_total_payment_by_filter(self, func: Union[Callable, None] = None) -> Dict[str, float]:
        result = defaultdict(float)
        for operation in self.get_operations_by_filter(func):
            result[operation.currency] += operation.payment
        return result

    def get_commissions(self) -> Dict[str, float]:
        return self.get_total_payment_by_filter(lambda o: o.operation_type in self.commission_operations_types)

    def get_service_commission(self):
        return self.get_total_payment_by_filter(
            lambda o: o.operation_type == OperationTypeWithCommission.SERVICECOMMISSION)

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
            lambda o: o.operation_type in (OperationTypeWithCommission.BUY, OperationTypeWithCommission.SELL, 'BuyCard')
        )

    def get_name_by_figi(self, figi):
        position = self.client.market.market_search_by_figi_get(figi).payload
        return f'{position.ticker} - {position.name} ({figi})'

    def get_profit(self) -> Dict[str, Dict[str, float]]:
        profit = dict()
        profit['dividend'] = self.get_total_payment_by_filter(
            lambda o: o.operation_type in (
                OperationTypeWithCommission.DIVIDEND, OperationTypeWithCommission.TAXDIVIDEND,
            )
        )
        profit['coupon'] = self.get_total_payment_by_filter(
            lambda o: o.operation_type in (OperationTypeWithCommission.COUPON, OperationTypeWithCommission.TAXCOUPON)
        )

        figi_total = defaultdict(lambda: defaultdict(float))
        for operation in self.get_operations_by_filter(
                lambda o: (o.operation_type in (
                        OperationTypeWithCommission.BUY, OperationTypeWithCommission.SELL, 'BuyCard') and
                           o.instrument_type != InstrumentType.CURRENCY
                )
        ):
            figi_total[operation.figi][operation.currency] += operation.payment + getattr(
                operation.commission, 'value', 0)

        figi_in_portfolio = {
            f.figi: (f.ticker, f.balance * f.average_position_price.value + f.expected_yield.value,
                     f.average_position_price.currency)
            for f in self.client.portfolio.portfolio_get().payload.positions
        }

        for figi, currency_sum in figi_total.items():
            for currency,  p_sum in currency_sum.items():
                if figi not in figi_in_portfolio:
                    profit[self.get_name_by_figi(figi)] = {currency: p_sum}
                elif figi_in_portfolio[figi][2] == currency:
                    profit[self.get_name_by_figi(figi)] = {currency: p_sum + figi_in_portfolio[figi][1]}

        return profit

    def get_statistics(self) -> Dict[str, str]:
        service_comission = self.get_service_commission()
        comission = self.get_commissions()
        profit = self.get_profit()
        total_profit = defaultdict(float)
        for figi, cur_val in profit.items():
            for currency, value in cur_val.items():
                total_profit[currency] += value

        for currency in total_profit.keys():
            total_profit[currency] += service_comission[currency]

        return {
            'Commissions and Taxes': format_dict(comission),
            'Service commissions': format_dict(service_comission),
            'Pay In': format_dict(self.get_pay_in()),
            'Pay Out': format_dict(self.get_pay_out()),
            'Pay Total': format_dict(self.get_pay_total()),
            'Operations': format_dict(self.get_total_operations_balance()),
            'Balance': format_dict(self.get_balance()),
            'Total Profit': format_dict_with_emoji(total_profit),
            'Detailed Profit': format_dict_with_emoji(profit)
        }

    def get_statistics_str(self) -> str:
        return '\n'.join(f'{k} -> {v}' for k, v in self.get_statistics().items())

    def get_portfolio_info(self):
        result = list()
        for item in self.client.portfolio.portfolio_get().payload.positions:
            result.append({
                'ticker': item.ticker,
                'name': self.get_name_by_figi(item.figi),
                'currency': item.average_position_price.currency,
                'current_total': round(item.average_position_price.value * item.balance + item.expected_yield.value, 2),
                'lots': item.balance,
                'avg_price': item.average_position_price.value,
            })
        return result
