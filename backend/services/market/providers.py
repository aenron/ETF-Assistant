"""Compose source adapters; MarketService supplies caches and orchestration."""

from services.market.tushare import TushareProviderMixin
from services.market.zhitu import ZhituProviderMixin
from services.market.sse import SseProviderMixin
from services.market.eastmoney import EastmoneyProviderMixin
from services.market.ths import ThsProviderMixin
from services.market.otc import OtcProviderMixin
from services.market.tencent import TencentProviderMixin
from services.market.sina import SinaProviderMixin

class MarketProviderMixin(TushareProviderMixin, ZhituProviderMixin, SseProviderMixin, EastmoneyProviderMixin, ThsProviderMixin, OtcProviderMixin, TencentProviderMixin, SinaProviderMixin):
    pass
